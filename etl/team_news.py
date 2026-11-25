"""Team news / player availability across all 5 leagues.

Combines three free, keyless feeds so every league has live availability:
  - FPL bootstrap-static (Premier League: chance_of_playing, minutes, starts, news)
  - SportsGambler (all 5 leagues: injured / suspended / doubtful + matches/G/A/return)
  - Transfermarkt verletztespieler (all 5 leagues: injuries, return dates, €M market value)

Merged team news is cross-checked by team and normalized player name,
computes unified regular-starter counts and attacking/defensive drag factors
for all 5 leagues, and caches raw payloads under data/raw/.

Usage:
    python -m etl.team_news
    python -m etl.team_news --leagues pl laliga
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import html as htmllib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
import unicodedata
import urllib.request

from .config import settings
from .logging_setup import get_logger
from .players import load_fpl_bootstrap
from .team_names import CANONICAL, canonicalize

log = get_logger(__name__)

SEASON_LABEL = f"{settings.live_season}/{str(int(settings.live_season) + 1)[-2:]}"
FPL_POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
_TRANSFER_NEWS_WORDS = ("joined", "loan", "departed", "free agent", "transferred")

SPORTSGAMBLER_URLS = {
    "pl": "https://www.sportsgambler.com/injuries/football/england-premier-league/",
    "laliga": "https://www.sportsgambler.com/injuries/football/spain-la-liga/",
    "bundesliga": "https://www.sportsgambler.com/injuries/football/germany-bundesliga/",
    "seriea": "https://www.sportsgambler.com/injuries/football/italy-serie-a/",
    "ligue1": "https://www.sportsgambler.com/injuries/football/france-ligue-1/",
}

TRANSFERMARKT_URLS = {
    "pl": "https://www.transfermarkt.com/premier-league/verletztespieler/wettbewerb/GB1",
    "laliga": "https://www.transfermarkt.com/laliga/verletztespieler/wettbewerb/ES1",
    "bundesliga": "https://www.transfermarkt.com/bundesliga/verletztespieler/wettbewerb/L1",
    "seriea": "https://www.transfermarkt.com/serie-a/verletztespieler/wettbewerb/IT1",
    "ligue1": "https://www.transfermarkt.com/ligue-1/verletztespieler/wettbewerb/FR1",
}

_SG_POS_MAP = {"G": "GK", "GK": "GK", "D": "DEF", "DEF": "DEF", "M": "MID", "MID": "MID", "F": "FWD", "A": "FWD", "FWD": "FWD"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    log.info("wrote_json", path=str(path))


def _norm_player(name: str) -> str:
    s = unicodedata.normalize("NFD", htmllib.unescape(name or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return " ".join(s.split())


def _player_match_key(name: str, pool_keys: dict[str, Any]) -> str | None:
    """Match normalized player name against pool_keys (exact then surname + initial)."""
    nk = _norm_player(name)
    if not nk:
        return None
    if nk in pool_keys:
        return nk
    parts = nk.split()
    if len(parts) >= 2:
        last, fi = parts[-1], parts[0][0]
        cands = [
            k for k in pool_keys
            if (k.split()[-1] == last or last in k.split()) and k.split()[0].startswith(fi)
        ]
        if len(cands) == 1:
            return cands[0]
        last_only = [k for k in pool_keys if k.split()[-1] == last]
        if len(last_only) == 1:
            return last_only[0]
    return None


def _fetch_html(url: str, cache_name: str, max_age_hours: float = 6.0) -> str | None:
    path = settings.raw_dir / cache_name
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if age_h <= max_age_hours:
            return path.read_text(errors="replace")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", errors="replace")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return text
    except Exception as exc:
        log.warning("html_fetch_failed", url=url, error=str(exc)[:160])
        if path.exists():
            return path.read_text(errors="replace")
        return None


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    t = re.sub(r"[^\d]", "", text)
    return int(t) if t else None


def _norm_tm_pos(role: str) -> str:
    r = (role or "").lower()
    if "goalkeeper" in r or "keeper" in r:
        return "GK"
    if any(w in r for w in ("back", "defender", "defence", "sweeper")):
        return "DEF"
    if any(w in r for w in ("midfield", "winger")):
        return "MID"
    if any(w in r for w in ("forward", "striker", "attack")):
        return "FWD"
    return "?"


def _parse_tm_value_m(raw: str | None) -> float | None:
    if not raw:
        return None
    txt = htmllib.unescape(raw).replace(",", ".").strip().lower()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([mk])", txt)
    if not m:
        return None
    val = float(m.group(1))
    return val if m.group(2) == "m" else val / 1000.0


def _parse_tm_return(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", raw)
    if not m:
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def parse_sportsgambler(html_text: str, league: str) -> list[dict]:
    """Parse SportsGambler league injury/suspension HTML into structured rows."""
    rows: list[dict] = []
    if not html_text or '<div class="injury-block">' not in html_text:
        return rows
    known = CANONICAL.get(league, set())
    for block in html_text.split('<div class="injury-block">')[1:]:
        m_team = re.search(r'<h3 class="injuries-title"[^>]*>(?:<a[^>]*>)?([^<]+)', block)
        if not m_team:
            continue
        team = canonicalize(m_team.group(1), league, "espn")
        if known and team not in known:
            continue
        for item in block.split('<div class="inj-row">')[1:]:
            m_type = re.search(r'class="inj-type\s+([^"]+)"', item)
            m_player = re.search(r'class="inj-player"[^>]*>([^<]+)<', item)
            if not m_player:
                continue
            player = htmllib.unescape(m_player.group(1)).strip()
            tcls = (m_type.group(1) if m_type else "").lower()
            if "question" in tcls:
                bucket, kind = "doubtful", "doubtful"
            elif "redcard" in tcls:
                bucket, kind = "out", "suspended"
            else:
                bucket, kind = "out", "injured"
            m_pos = re.search(r'class="inj-position[^"]*"[^>]*>([^<]+)<', item)
            m_g = re.search(r'class="inj-game[^"]*"[^>]*>([^<]+)<', item)
            m_go = re.search(r'class="inj-goals[^"]*"[^>]*>([^<]+)<', item)
            m_a = re.search(r'class="inj-assist[^"]*"[^>]*>([^<]+)<', item)
            m_info = re.search(r'class="inj-info"[^>]*>([^<]*)<', item)
            m_ret = re.search(r'class="inj-return[^"]*"[^>]*>([^<]*)<', item)
            ret = htmllib.unescape(m_ret.group(1)).strip() if m_ret else ""
            if ret == "-":
                ret = ""
            rows.append({
                "team": team,
                "player": player,
                "bucket": bucket,
                "kind": kind,
                "position": _SG_POS_MAP.get((m_pos.group(1) if m_pos else "").strip().upper(), "?"),
                "matches": _to_int(m_g.group(1) if m_g else None) or 0,
                "goals": _to_int(m_go.group(1) if m_go else None) or 0,
                "assists": _to_int(m_a.group(1) if m_a else None) or 0,
                "reason": htmllib.unescape(m_info.group(1)).strip() if m_info else "",
                "expected_return": ret or None,
                "source": "SportsGambler",
            })
    return rows


def parse_transfermarkt(html_text: str, league: str) -> list[dict]:
    """Parse Transfermarkt verletztespieler HTML into structured injury rows."""
    rows: list[dict] = []
    if not html_text:
        return rows
    known = CANONICAL.get(league, set())
    for chunk in re.split(r'<tr class="(?:odd|even)">', html_text)[1:]:
        m_player = re.search(r'class="hauptlink"[^>]*>\s*<a[^>]*title="([^"]+)"', chunk)
        m_club = re.search(r'<td class="zentriert no-border-rechts"><a title="([^"]+)"', chunk)
        if not m_player or not m_club:
            continue
        team = canonicalize(m_club.group(1), league, "api")
        if known and team not in known:
            continue
        player = htmllib.unescape(m_player.group(1)).strip()
        pos_m = re.search(r'</tr>\s*<tr>\s*<td>([^<]+)</td>', chunk)
        links = re.findall(r'<td class="links">(.*?)</td>', chunk)
        zent = re.findall(r'<td class="zentriert">(.*?)</td>', chunk)
        val_m = re.search(r'<td class="rechts">(.*?)</td>', chunk)
        reason = htmllib.unescape(re.sub(r"<[^>]+>", "", links[0])).strip() if links else ""
        ret = _parse_tm_return(zent[-1] if zent else None)
        rows.append({
            "team": team,
            "player": player,
            "bucket": "out",
            "kind": "injured",
            "position": _norm_tm_pos(pos_m.group(1) if pos_m else ""),
            "reason": reason,
            "expected_return": ret,
            "market_value_m": _parse_tm_value_m(val_m.group(1) if val_m else None),
            "source": "Transfermarkt",
        })
    return rows


def _fetch_transfermarkt(league: str) -> list[dict]:
    url = TRANSFERMARKT_URLS.get(league)
    if not url:
        return []
    html_p1 = _fetch_html(url, f"transfermarkt_{league}.html")
    if not html_p1:
        return []
    rows = parse_transfermarkt(html_p1, league)
    # Collect subsequent pagination pages (typically 2-3 pages for 50-100 players).
    pages = sorted({
        int(p) for p in re.findall(r"verletztespieler/[^\"']*page=(\d+)", html_p1)
        if int(p) > 1
    })
    for pg in pages[:5]:
        sep = "&" if "?" in url else "?"
        html_pg = _fetch_html(f"{url}{sep}page={pg}", f"transfermarkt_{league}_p{pg}.html")
        if html_pg:
            rows.extend(parse_transfermarkt(html_pg, league))
    return rows


# ---------------------------------------------------------------------------
# Premier League: FPL injury / availability flags
# ---------------------------------------------------------------------------

def _flagged(el: dict) -> str | None:
    """Return 'out' / 'doubtful' / None for one FPL element."""
    status = el.get("status")
    news = (el.get("news") or "").lower()
    if status == "u" and any(w in news for w in _TRANSFER_NEWS_WORDS):
        return None
    this_round = el.get("chance_of_playing_this_round")
    next_round = el.get("chance_of_playing_next_round")
    if status in ("i", "s", "u") or this_round == 0:
        return "out"
    if status == "d" or (this_round is not None and this_round < 100) \
            or (next_round is not None and next_round < 100):
        return "doubtful"
    return None


def _compute_team_drags(team_entries: list[dict], squad_pool: list[dict]) -> tuple[int, float, float]:
    """Compute (key_absences, drag_att, drag_def) uniformly for one team."""
    if squad_pool:
        by_usage = sorted(
            squad_pool,
            key=lambda p: (p.get("minutes") or 0, p.get("starts") or 0, p.get("matches") or 0),
            reverse=True,
        )
        starter_names = {_norm_player(p["name"]) for p in by_usage[:11] if p.get("name")}
        total_starter_usage = sum(
            (p.get("minutes") or (p.get("starts") or p.get("matches") or 0) * 90)
            for p in by_usage[:11]
        ) or 1.0
        team_ga = max(5.0, sum((p.get("goals") or 0) + (p.get("assists") or 0) for p in squad_pool))
    else:
        starter_names = set()
        total_starter_usage = 1.0
        team_ga = max(12.0, sum((e.get("goals") or 0) + (e.get("assists") or 0) for e in team_entries))

    drag_att = 0.0
    drag_def = 0.0
    key_absences = 0

    for e in team_entries:
        # Infer starter status using either FPL/ESPN usage or fallback match/market-value thresholds.
        nk = _norm_player(e.get("player", ""))
        mins = e.get("minutes") or ((e.get("matches") or 0) * 75)
        mv = e.get("market_value_m") or 0.0
        is_starter = bool(e.get("regular_starter")) or (nk in starter_names) or (mv >= 18.0)
        e["regular_starter"] = is_starter
        if is_starter:
            key_absences += 1

        chance = e.get("chance_this_round")
        if e.get("bucket") == "out" or chance == 0:
            q = 1.0
        elif chance is not None:
            try:
                q = max(0.0, 1.0 - float(chance) / 100.0)
            except (ValueError, TypeError):
                q = 0.45
        else:
            q = 0.45

        if total_starter_usage > 1.0 and mins > 0:
            m_share = min(0.15, mins / total_starter_usage)
        elif mv > 0:
            m_share = min(0.14, max(0.03, mv / 240.0))
        elif is_starter:
            m_share = 0.065
        else:
            m_share = 0.02

        ga = (e.get("goals") or 0) + (e.get("assists") or 0)
        goal_share = min(0.25, ga / team_ga)
        pos = e.get("position", "?")
        active_enough = is_starter or mins >= 270 or (e.get("matches") or 0) >= 3 or mv >= 12.0
        if not active_enough:
            continue

        if pos in ("MID", "FWD"):
            drag_att += q * (0.6 * m_share + 0.4 * goal_share)
        elif pos in ("GK", "DEF"):
            gk_mult = 1.2 if pos == "GK" else 1.0
            drag_def += q * min(0.18, m_share * gk_mult)
        elif ga > 0:
            drag_att += q * (0.5 * m_share + 0.3 * goal_share)

    return key_absences, round(float(min(0.40, max(0.0, drag_att))), 4), round(float(min(0.40, max(0.0, drag_def))), 4)


def _load_squad_context(league: str) -> dict[str, list[dict]]:
    """Per-team player stats from FPL (PL) or ESPN roster file for starter/usage context."""
    d = settings.data_dir
    out: dict[str, list[dict]] = {}
    if league == "pl" and (d / "players_pl.json").exists():
        try:
            pl = json.loads((d / "players_pl.json").read_text())
            for p in pl.get("players", []):
                out.setdefault(p.get("team", ""), []).append(p)
            return out
        except Exception:
            pass
    sq_path = d / f"squad_players_{league}.json"
    if sq_path.exists():
        try:
            sq = json.loads(sq_path.read_text())
            for p in sq.get("players", []):
                out.setdefault(p.get("team", ""), []).append(p)
        except Exception:
            pass
    return out


def build_team_news_pl(bootstrap: dict) -> dict:
    """Build PL availability from FPL bootstrap-static (preserving unit-test contract)."""
    teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}
    elements = bootstrap.get("elements", [])

    by_team: dict[str, list[dict]] = {}
    for el in elements:
        team = canonicalize(teams.get(el.get("team"), ""), "pl", source="fpl")
        by_team.setdefault(team, []).append(el)

    team_news: dict[str, dict] = {}
    for team in sorted(by_team):
        squad = by_team[team]
        sorted_squad = sorted(squad, key=lambda e: e.get("minutes") or 0, reverse=True)
        starters = {el["id"] for el in sorted_squad[:11]}
        starter_mins = sum(el.get("minutes") or 0 for el in sorted_squad[:11]) or 1.0
        team_goals = sum(el.get("goals_scored") or 0 for el in squad) or 1.0
        team_assists = sum(el.get("assists") or 0 for el in squad) or 1.0

        entries: list[dict] = []
        for el in squad:
            flag = _flagged(el)
            if flag is None:
                continue
            name = f"{el.get('first_name', '')} {el.get('second_name', '')}".strip()
            is_starter = el.get("id") in starters
            pos = FPL_POSITIONS.get(el.get("element_type"), "?")
            news_txt = (el.get("news") or "").strip()
            kind = "suspended" if (el.get("status") == "s" or "suspend" in news_txt.lower()) else (
                "injured" if flag == "out" else "doubtful"
            )
            entries.append({
                "player": name,
                "status": el.get("status"),
                "kind": kind,
                "bucket": flag,
                "chance_this_round": el.get("chance_of_playing_this_round"),
                "chance_next_round": el.get("chance_of_playing_next_round"),
                "news": news_txt,
                "reason": news_txt,
                "regular_starter": is_starter,
                "position": pos,
                "minutes": el.get("minutes") or 0,
                "goals": el.get("goals_scored") or 0,
                "assists": el.get("assists") or 0,
                "sources": ["FPL"],
            })

        squad_pool = [{
            "name": f"{el.get('first_name', '')} {el.get('second_name', '')}".strip(),
            "minutes": el.get("minutes") or 0,
            "goals": el.get("goals_scored") or 0,
            "assists": el.get("assists") or 0,
        } for el in sorted_squad]
        # Preserve exact minutes math when FPL minutes are available.
        drag_att = drag_def = 0.0
        for e in entries:
            chance = e["chance_this_round"]
            if e["bucket"] == "out" or chance == 0:
                q = 1.0
            elif chance is not None:
                try:
                    q = max(0.0, 1.0 - (float(chance) / 100.0))
                except (ValueError, TypeError):
                    q = 0.5
            else:
                q = 0.5
            mins = e["minutes"]
            m_share = min(0.15, mins / starter_mins)
            goal_share = (e["goals"] + e["assists"]) / (team_goals + team_assists)
            if e["position"] in ("MID", "FWD") and (e["regular_starter"] or mins >= 270):
                drag_att += q * (0.6 * m_share + 0.4 * min(0.25, goal_share))
            if e["position"] in ("GK", "DEF") and (e["regular_starter"] or mins >= 270):
                drag_def += q * m_share

        out = [e for e in entries if e["bucket"] == "out"]
        doubtful = [e for e in entries if e["bucket"] != "out"]
        key_absences = sum(1 for e in entries if e["regular_starter"])
        team_news[team] = {
            "out": out,
            "doubtful": doubtful,
            "key_absences": key_absences,
            "drag_att": round(float(min(0.40, max(0.0, drag_att))), 4),
            "drag_def": round(float(min(0.40, max(0.0, drag_def))), 4),
        }

    return {
        "league": "pl",
        "source": "FPL API (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("Injury and suspension flags merged across FPL, SportsGambler, "
                  "and Transfermarkt where available."),
        "teams": team_news,
    }


def merge_multi_source_news(
    league: str,
    base_teams: dict[str, dict] | None,
    sg_rows: list[dict],
    tm_rows: list[dict],
    squad_ctx: dict[str, list[dict]],
) -> dict:
    """Merge SportsGambler + Transfermarkt (+ FPL for PL) into unified team news."""
    teams_out: dict[str, dict] = {}
    all_teams = set(base_teams or {}) | {r["team"] for r in sg_rows} | {r["team"] for r in tm_rows}

    by_team_sg: dict[str, list[dict]] = {}
    for r in sg_rows:
        by_team_sg.setdefault(r["team"], []).append(r)
    by_team_tm: dict[str, list[dict]] = {}
    for r in tm_rows:
        by_team_tm.setdefault(r["team"], []).append(r)

    for team in sorted(all_teams):
        merged: dict[str, dict] = {}
        base = (base_teams or {}).get(team, {})
        for bucket in ("out", "doubtful"):
            for e in base.get(bucket, []):
                entry = dict(e)
                entry.setdefault("bucket", bucket)
                entry.setdefault("kind", "suspended" if entry.get("status") == "s" else (
                    "injured" if bucket == "out" else "doubtful"
                ))
                entry.setdefault("sources", ["FPL"])
                merged[_norm_player(entry["player"])] = entry

        # Reconcile SportsGambler entries
        for r in by_team_sg.get(team, []):
            mk = _player_match_key(r["player"], merged)
            if mk:
                cur = merged[mk]
                if "SportsGambler" not in cur.get("sources", []):
                    cur.setdefault("sources", []).append("SportsGambler")
                # Prefer explicit suspended/out severity or enrich reason/return
                if r["kind"] == "suspended":
                    cur["kind"] = "suspended"
                    cur["bucket"] = "out"
                elif r["bucket"] == "out" and cur.get("bucket") != "out":
                    cur["bucket"] = "out"
                    cur["kind"] = r["kind"]
                if not cur.get("reason") and r.get("reason"):
                    cur["reason"] = r["reason"]
                if not cur.get("expected_return") and r.get("expected_return"):
                    cur["expected_return"] = r["expected_return"]
                if cur.get("position", "?") == "?" and r.get("position", "?") != "?":
                    cur["position"] = r["position"]
                for k in ("matches", "goals", "assists"):
                    if (cur.get(k) or 0) == 0 and (r.get(k) or 0) > 0:
                        cur[k] = r[k]
            else:
                merged[_norm_player(r["player"])] = {
                    "player": r["player"],
                    "bucket": r["bucket"],
                    "kind": r["kind"],
                    "position": r["position"],
                    "matches": r["matches"],
                    "goals": r["goals"],
                    "assists": r["assists"],
                    "reason": r["reason"],
                    "news": r["reason"],
                    "expected_return": r["expected_return"],
                    "chance_this_round": 0 if r["bucket"] == "out" else 50,
                    "regular_starter": False,
                    "sources": ["SportsGambler"],
                }

        # Reconcile Transfermarkt entries (adds €M value + non-truncated reason/return)
        for r in by_team_tm.get(team, []):
            mk = _player_match_key(r["player"], merged)
            if mk:
                cur = merged[mk]
                if "Transfermarkt" not in cur.get("sources", []):
                    cur.setdefault("sources", []).append("Transfermarkt")
                if r.get("market_value_m") is not None:
                    cur["market_value_m"] = r["market_value_m"]
                if r.get("reason") and len(r["reason"]) > len(cur.get("reason") or ""):
                    cur["reason"] = r["reason"]
                if not cur.get("expected_return") and r.get("expected_return"):
                    cur["expected_return"] = r["expected_return"]
                if cur.get("position", "?") == "?" and r.get("position", "?") != "?":
                    cur["position"] = r["position"]
            else:
                merged[_norm_player(r["player"])] = {
                    "player": r["player"],
                    "bucket": "out",
                    "kind": "injured",
                    "position": r["position"],
                    "matches": 0,
                    "goals": 0,
                    "assists": 0,
                    "reason": r["reason"],
                    "news": r["reason"],
                    "expected_return": r["expected_return"],
                    "market_value_m": r.get("market_value_m"),
                    "chance_this_round": 0,
                    "regular_starter": False,
                    "sources": ["Transfermarkt"],
                }

        # Enrich entries with ESPN / official squad stats when minutes/starts missing
        sq_list = squad_ctx.get(team, [])
        sq_map = {_norm_player(p.get("name", "")): p for p in sq_list if p.get("name")}
        entries = list(merged.values())
        for e in entries:
            sk = _player_match_key(e["player"], sq_map)
            if sk:
                sp = sq_map[sk]
                if e.get("position", "?") == "?" and sp.get("position", "?") != "?":
                    e["position"] = sp["position"]
                if not e.get("minutes") and sp.get("minutes"):
                    e["minutes"] = sp["minutes"]
                if not e.get("matches") and (sp.get("appearances") or sp.get("starts")):
                    e["matches"] = sp.get("appearances") or sp.get("starts") or 0
                if not e.get("goals") and sp.get("goals"):
                    e["goals"] = sp["goals"]
                if not e.get("assists") and sp.get("assists"):
                    e["assists"] = sp["assists"]

        # Keep FPL's native drag when available on PL; add incremental non-FPL drag only via unified calc for non-PL
        key_abs, drag_att, drag_def = _compute_team_drags(entries, sq_list)
        if league == "pl" and base and not any(
            s in ("SportsGambler", "Transfermarkt")
            for e in entries for s in e.get("sources", [])
        ):
            key_abs = int(base.get("key_absences", key_abs))
            drag_att = float(base.get("drag_att", drag_att))
            drag_def = float(base.get("drag_def", drag_def))

        out_list = sorted(
            [e for e in entries if e.get("bucket") == "out"],
            key=lambda x: (-(1 if x.get("regular_starter") else 0), -(x.get("market_value_m") or 0.0), x["player"]),
        )
        doubt_list = sorted(
            [e for e in entries if e.get("bucket") != "out"],
            key=lambda x: (-(1 if x.get("regular_starter") else 0), -(x.get("market_value_m") or 0.0), x["player"]),
        )
        teams_out[team] = {
            "out": out_list,
            "doubtful": doubt_list,
            "key_absences": key_abs,
            "drag_att": drag_att,
            "drag_def": drag_def,
        }

    srcs = []
    if league == "pl":
        srcs.append("FPL API")
    if sg_rows:
        srcs.append("SportsGambler")
    if tm_rows:
        srcs.append("Transfermarkt")
    source_label = " + ".join(srcs) if srcs else "none"

    return {
        "league": league,
        "source": source_label,
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("Multi-source player availability combining SportsGambler "
                  "(injured, suspended, doubtful), Transfermarkt (€M valuation "
                  "and return dates), and FPL for Premier League."),
        "teams": teams_out,
    }


def run_league(league: str) -> Path:
    base_teams = None
    if league == "pl":
        bootstrap = load_fpl_bootstrap()
        base_teams = build_team_news_pl(bootstrap)["teams"]
    sg_html = _fetch_html(SPORTSGAMBLER_URLS[league], f"sportsgambler_{league}.html")
    sg_rows = parse_sportsgambler(sg_html, league) if sg_html else []
    tm_rows = _fetch_transfermarkt(league)
    squad_ctx = _load_squad_context(league)
    payload = merge_multi_source_news(league, base_teams, sg_rows, tm_rows, squad_ctx)
    out = settings.data_dir / f"team_news_{league}.json"
    _write_json(out, payload)
    n_key = sum(t["key_absences"] for t in payload["teams"].values())
    n_out = sum(len(t["out"]) for t in payload["teams"].values())
    n_doubt = sum(len(t["doubtful"]) for t in payload["teams"].values())
    log.info("team_news_done", league=league, source=payload["source"],
             teams=len(payload["teams"]), out=n_out, doubtful=n_doubt, key_absences=n_key)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-source team news / availability across all 5 leagues."
    )
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs (default: all)")
    args = parser.parse_args(argv)

    ok = True
    for league in args.leagues:
        try:
            if league in SPORTSGAMBLER_URLS:
                run_league(league)
            else:
                raise ValueError(f"unknown league: {league}")
        except Exception as exc:
            log.error("team_news_failed", league=league, error=str(exc)[:200])
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
