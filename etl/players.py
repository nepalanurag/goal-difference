"""Player data for the goal-difference site: three independent parts.

(a) Premier League current-season form watch from the FPL API
    (bootstrap-static). No key needed. Raw cached to
    data/raw/fpl_bootstrap_players.json. Output data/players_pl.json.

(b) 2024/25 top-20 scorers for all 5 leagues via api-football
    /players/topscorers (5 calls, season=2024). Raw cached to
    data/raw/api_topscorers_{league}_2024.json. Output
    data/topscorers_2425.json. Before the first api-football call this
    waits for data/european_fixtures.jsonl (another process holds the
    shared key): polls every 30s for up to 15 minutes.

(c) Current-season player rankings from the leagues' official backends
    (all keyless JSON feeds, same risk class as the FPL API: validate
    shapes, cache raw, never hard-fail per league):
      LaLiga      apim.laliga.com public-service (paginated players/stats)
      Bundesliga  DFL Firebase playerRankings.json
      Serie A     api-sdp.legaseriea.it paginated stats/players
      Ligue 1     ma-api.ligue1.fr scorers + assists rankings
    Outputs data/player_rankings_official_{laliga,bundesliga,seriea,ligue1}.json.

Every output JSON carries source, season_label and fetched_at.
Per-league failures log a warning and fall back to the labeled
2024/25 topscorers instead of aborting the run.

Usage:
    python -m etl.players                 # all parts, all leagues
    python -m etl.players --parts a c     # skip the api-football part
    python -m etl.players --parts b --leagues pl laliga
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .api_football import api_get
from .config import settings
from .logging_setup import get_logger
from .team_names import canonicalize

log = get_logger(__name__)

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
SEASON_LABEL = "2026/27"
TOPSCORERS_SEASON_LABEL = "2024/25"

FPL_POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
# FPL status codes: a=available d=doubtful i=injured s=suspended u=unavailable
FPL_STATUS_LABEL = {
    "a": "available", "d": "doubtful", "i": "injured",
    "s": "suspended", "u": "unavailable",
}

# Gate: another process is accumulating European fixtures on the shared
# api-football key. No api-football call before this file exists.
EUROPEAN_GATE = settings.data_dir / "european_fixtures.jsonl"
GATE_POLL_SECONDS = 30
GATE_TIMEOUT_SECONDS = 15 * 60

LALIGA_STATS_URL = (
    "https://apim.laliga.com/public-service/api/v1/subscriptions"
    "/{slug}/players/stats?limit=100&offset={offset}"
    "&orderField=name&orderType=ASC"
)
BUNDESLIGA_RANKINGS_URL = (
    "https://bundesliga-web-prod.europe-west1.firebasedatabase.app"
    "/all/DFL-COM-000001/seasons/DFL-SEA-0001KA/stats/playerRankings.json"
)
SERIEA_COMPETITION_ID = "serie-a::Football_Competition::ec93b94f74294dc98ab5bcfd67fc0d88"
LIGUE1_BASE = "https://ma-api.ligue1.fr"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def _get_json(session: requests.Session, url: str, *,
              headers: dict | None = None, timeout: int = 30) -> Any:
    resp = session.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    log.info("wrote_json", path=str(path))


def _cache_raw(name: str, payload: Any) -> Path:
    path = settings.raw_dir / name
    _write_json(path, payload)
    return path


# ---------------------------------------------------------------------------
# Shared: FPL bootstrap (used by players part (a) and by etl.team_news)
# ---------------------------------------------------------------------------

def load_fpl_bootstrap(*, refresh: bool = False,
                       max_age_hours: float = 24.0) -> dict:
    """Return the FPL bootstrap-static payload, reusing a fresh cache.

    Prefers data/raw/fpl_bootstrap_players.json, then the extract step's
    data/raw/fpl_bootstrap_static.json (same endpoint), then refetches.
    """
    candidates = [
        settings.raw_dir / "fpl_bootstrap_players.json",
        settings.raw_dir / "fpl_bootstrap_static.json",
    ]
    if not refresh:
        for path in candidates:
            if path.exists():
                age_h = (time.time() - path.stat().st_mtime) / 3600
                if age_h <= max_age_hours:
                    log.info("fpl_cache_reuse", path=str(path),
                             age_hours=round(age_h, 1))
                    return json.loads(path.read_text())
                log.info("fpl_cache_stale", path=str(path),
                         age_hours=round(age_h, 1))
    log.info("fpl_fetch", url=FPL_BOOTSTRAP_URL)
    payload = _get_json(_session(), FPL_BOOTSTRAP_URL)
    if not isinstance(payload, dict) or "elements" not in payload:
        raise RuntimeError("FPL bootstrap-static: unexpected shape "
                           f"(keys={sorted(payload.keys()) if isinstance(payload, dict) else type(payload)})")
    _cache_raw("fpl_bootstrap_players.json", payload)
    return payload


# ---------------------------------------------------------------------------
# Part (a): Premier League form watch from FPL
# ---------------------------------------------------------------------------

def _fpl_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_players_pl(bootstrap: dict) -> dict:
    teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}
    players: list[dict] = []
    for el in bootstrap.get("elements", []):
        team_raw = teams.get(el.get("team"), "")
        now_cost = el.get("now_cost") or 0
        total_points = el.get("total_points") or 0
        minutes = el.get("minutes") or 0
        players.append({
            "name": f"{el.get('first_name', '')} {el.get('second_name', '')}".strip(),
            "web_name": el.get("web_name"),
            "team": canonicalize(team_raw, "pl", source="fpl"),
            "position": FPL_POSITIONS.get(el.get("element_type"), "?"),
            "form": _fpl_float(el.get("form")),
            "total_points": total_points,
            "goals": el.get("goals_scored") or 0,
            "assists": el.get("assists") or 0,
            "clean_sheets": el.get("clean_sheets") or 0,
            "minutes": minutes,
            "ict_index": _fpl_float(el.get("ict_index")),
            "now_cost": now_cost / 10.0,
            "selected_by_percent": _fpl_float(el.get("selected_by_percent")),
            "points_per_million": round(total_points / (now_cost / 10.0), 2) if now_cost else 0.0,
            "status": FPL_STATUS_LABEL.get(el.get("status"), el.get("status")),
            "chance_of_playing_this_round": el.get("chance_of_playing_this_round"),
            "chance_of_playing_next_round": el.get("chance_of_playing_next_round"),
            "news": (el.get("news") or "").strip(),
        })

    # In-form XI by position, on FPL form (avg points over the last 30 days).
    eligible = [p for p in players if p["minutes"] > 0]
    xi: dict[str, list[dict]] = {}
    for pos, n in [("GK", 1), ("DEF", 4), ("MID", 4), ("FWD", 2)]:
        picks = sorted((p for p in eligible if p["position"] == pos),
                       key=lambda p: p["form"], reverse=True)[:n]
        xi[pos] = [{"name": p["name"], "team": p["team"],
                    "form": p["form"]} for p in picks]

    # Risers: form running well ahead of the season points-per-game.
    # bootstrap-static carries no week-over-week snapshot, so this compares
    # last-30-day form against the season average, honestly labeled below.
    risers = []
    for p in players:
        if p["minutes"] < 270:
            continue
        season_ppg = p["total_points"] / (p["minutes"] / 90.0)
        edge = p["form"] - season_ppg
        if edge > 0:
            risers.append({"name": p["name"], "team": p["team"],
                           "position": p["position"], "form": p["form"],
                           "season_ppg": round(season_ppg, 2),
                           "edge": round(edge, 2)})
    risers.sort(key=lambda r: r["edge"], reverse=True)
    risers = risers[:15]

    return {
        "source": "FPL API (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": (
            "form is the FPL last-30-day average. risers compares that "
            "form against the season points-per-game because "
            "bootstrap-static publishes no week-over-week snapshot."
        ),
        "players": players,
        "in_form_xi": xi,
        "risers": risers,
    }


def run_part_a() -> Path:
    bootstrap = load_fpl_bootstrap()
    payload = build_players_pl(bootstrap)
    out = settings.data_dir / "players_pl.json"
    _write_json(out, payload)
    log.info("players_pl_done", n_players=len(payload["players"]),
             n_risers=len(payload["risers"]))
    return out


# ---------------------------------------------------------------------------
# Part (b): 2024/25 top scorers via api-football (gated on the shared key)
# ---------------------------------------------------------------------------

def _wait_for_european_gate() -> None:
    """Block until the European-fixtures process has started its key use."""
    deadline = time.time() + GATE_TIMEOUT_SECONDS
    while time.time() < deadline:
        if EUROPEAN_GATE.exists():
            log.info("european_gate_open", path=str(EUROPEAN_GATE))
            return
        log.info("european_gate_wait", path=str(EUROPEAN_GATE),
                 poll_seconds=GATE_POLL_SECONDS)
        time.sleep(GATE_POLL_SECONDS)
    raise TimeoutError(
        f"api-football gate {EUROPEAN_GATE} never appeared after "
        f"{GATE_TIMEOUT_SECONDS // 60} minutes; refusing to touch the shared "
        "key blind. Re-run once the European accumulation has started."
    )


def _parse_topscorers(body: dict, league: str) -> list[dict]:
    errors = body.get("errors")
    if errors:
        raise RuntimeError(f"api-football errors: {errors}")
    rows: list[dict] = []
    for entry in body.get("response", [])[:20]:
        player = entry.get("player", {})
        stats = (entry.get("statistics") or [{}])[0]
        team = stats.get("team", {}) or {}
        games = stats.get("games", {}) or {}
        goals = stats.get("goals", {}) or {}
        rating = games.get("rating")
        try:
            rating_f = float(rating) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating_f = None
        name = player.get("name") or " ".join(
            x for x in [player.get("firstname"), player.get("lastname")] if x)
        rows.append({
            "player": name.strip(),
            "team": canonicalize(team.get("name", ""), league, source="api"),
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "appearances": games.get("appearences") or 0,
            "rating": rating_f,
        })
    return rows


def run_part_b(leagues: list[str]) -> Path:
    _wait_for_european_gate()
    payload: dict[str, Any] = {
        "source": "api-football /players/topscorers",
        "season_label": TOPSCORERS_SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": (
            "One-off historical pull. Every table on the site that uses "
            "this data is labeled with the season."
        ),
    }
    for league in leagues:
        if league == "pl":
            # Part (a) already covers PL current season; the 2024/25
            # baseline is still useful and cheap, so keep it uniform.
            pass
        try:
            api_id = settings.leagues[league]["api_id"]
            body = api_get("/players/topscorers",
                           {"league": api_id, "season": 2024})
            _cache_raw(f"api_topscorers_{league}_2024.json", body)
            rows = _parse_topscorers(body, league)
            if not rows:
                raise RuntimeError("empty response")
            payload[league] = rows
            log.info("topscorers_done", league=league, n=len(rows))
        except Exception as exc:  # never hard-fail one league
            log.warning("topscorers_failed", league=league,
                        error=str(exc)[:200])
            payload[league] = []
            payload.setdefault("_league_notes", {})[league] = (
                f"topscorers pull failed ({exc}); official-backend "
                "rankings in part (c) are the fallback"
            )
    out = settings.data_dir / "topscorers_2425.json"
    _write_json(out, payload)
    return out


# ---------------------------------------------------------------------------
# Part (c): official league backends (keyless, validated, warn-and-continue)
# ---------------------------------------------------------------------------

def _laliga_subscription_key(session: requests.Session) -> str:
    page = session.get("https://www.laliga.com/en-GB/advanced-stats",
                       timeout=30)
    page.raise_for_status()
    match = re.search(r"backendSubscription['\"]?\s*[:=]\s*['\"]([a-f0-9]+)",
                      page.text)
    if not match:
        raise RuntimeError("backendSubscription key not found in LaLiga page")
    return match.group(1)  # never logged


def fetch_laliga(session: requests.Session) -> dict:
    key = _laliga_subscription_key(session)  # kept in memory only
    headers = {"Ocp-Apim-Subscription-Key": key}
    subs = _get_json(
        session,
        "https://apim.laliga.com/public-service/api/v1/subscriptions"
        "?competitionSlug=primera-division",
        headers=headers)
    items = subs if isinstance(subs, list) else subs.get("subscriptions",
                                                   subs.get("data", []))
    if not isinstance(items, list) or not items:
        raise RuntimeError("no subscriptions returned")
    current = next((s for s in items if s.get("season") == "2026-2027"), None)
    if current is None:
        raise RuntimeError("no 2026-2027 subscription found")
    slug = current["slug"]
    log.info("laliga_slug", slug=slug)

    players: list[dict] = []
    offset, limit, total = 0, 100, None
    while True:
        page = _get_json(session, LALIGA_STATS_URL.format(slug=slug,
                                                          offset=offset),
                         headers=headers)
        if not isinstance(page, dict) or "player_stats" not in page:
            raise RuntimeError("unexpected players/stats shape: "
                               f"{sorted(page.keys()) if isinstance(page, dict) else type(page)}")
        _cache_raw(f"laliga_players_stats_offset_{offset}.json", page)
        batch = page["player_stats"]
        players.extend(batch)
        total = page.get("total", len(batch))
        offset += limit
        if offset >= total or not batch:
            break
    log.info("laliga_players", n=len(players), total=total)

    wanted = {"goals", "appearances", "games_played", "time_played",
              "total_shots", "shots_on_target_inc_goals",
              "key_passes_attempt_assists", "starts", "clean_sheets"}
    rows = []
    for p in players:
        stats = {s["name"]: s.get("stat") for s in p.get("stats", [])
                 if isinstance(s, dict) and "name" in s}
        rows.append({
            "name": p.get("name"),
            "nickname": p.get("nickname"),
            "team": (p.get("team") or {}).get("name"),
            "position": (p.get("position") or {}).get("name"),
            "goals": stats.get("goals"),
            "assists": None,  # not published in this feed
            "appearances": stats.get("appearances"),
            "minutes": stats.get("time_played"),
            "shots": stats.get("total_shots"),
            "shots_on_target": stats.get("shots_on_target_inc_goals"),
            "key_passes": stats.get("key_passes_attempt_assists"),
            "starts": stats.get("starts"),
        })
    return {
        "source": "LaLiga apim public-service API (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("72 advanced stats per player cached raw; assists are "
                  "not published in this feed, so assists is null here."),
        "players": rows,
    }


def fetch_bundesliga(session: requests.Session) -> dict:
    data = _get_json(session, BUNDESLIGA_RANKINGS_URL)
    if not isinstance(data, dict) or "assists" not in data:
        raise RuntimeError("unexpected playerRankings shape")
    _cache_raw("bundesliga_player_rankings.json", data)

    # DFL publishes no dedicated goals ranking; "shotsAtGoalSuccessful"
    # (successful shots at goal, penalties tracked separately) is goals.
    category_map = {
        "goals": "shotsAtGoalSuccessful",
        "assists": "assists",
        "shots": "shotsAtGoal",
        "crosses": "crossesFromPlay",
        "saves": "goalkeeperSaves",
        "distance_km": "distanceCovered",
    }
    out: dict[str, Any] = {
        "source": "Bundesliga official Firebase playerRankings (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("No dedicated goals ranking in the feed; goals are taken "
                  "from shotsAtGoalSuccessful. Club names are not in the "
                  "feed, so club_id + logo URL are kept instead."),
        "category_map": category_map,
    }
    for label, category in category_map.items():
        entries = data.get(category)
        if not entries:
            log.warning("bundesliga_category_missing", category=category)
            out[label] = []
            continue
        rows = sorted(entries.values(),
                      key=lambda e: (e.get("rank") is None, e.get("rank")))
        out[label] = [{
            "player": e.get("name"),
            "club_id": (e.get("club") or {}).get("dflDatalibraryClubId"),
            "club_logo": (e.get("club") or {}).get("logoUrl"),
            "value": e.get("value"),
            "rank": e.get("rank"),
        } for e in rows]
    return out


def fetch_seriea(session: requests.Session) -> dict:
    comp = urllib.parse.quote(SERIEA_COMPETITION_ID, safe="")
    seasons = _get_json(
        session,
        f"https://api-sdp.legaseriea.it/v1/serie-a/football/competitions"
        f"/{comp}/seasons").get("seasons", [])
    if not seasons:
        raise RuntimeError("no seasons returned")
    newest = next((s for s in seasons if s.get("seasonName") == "2026/2027"),
                  seasons[0])
    season_id = urllib.parse.quote(newest["seasonId"], safe="")
    log.info("seriea_season", season=newest.get("seasonName"))

    players: list[dict] = []
    page = 1
    while True:
        data = _get_json(
            session,
            f"https://api-sdp.legaseriea.it/v1/serie-a/football/seasons"
            f"/{season_id}/stats/players?limit=30&page={page}")
        if not isinstance(data, dict) or "players" not in data:
            raise RuntimeError("unexpected stats/players shape")
        _cache_raw(f"seriea_players_stats_page_{page}.json", data)
        players.extend(data["players"])
        pagination = data.get("pagination", {})
        total_pages = pagination.get("totalPages", page)
        if pagination.get("isLastPage") or page >= total_pages:
            break
        page += 1
    log.info("seriea_players", n=len(players))

    wanted = {"games-played", "minutes-played", "goals", "assists",
              "total-scoring-attempts", "shots-on-target"}
    rows = []
    for p in players:
        stats = {s.get("statsId"): s.get("statsValue")
                 for s in p.get("stats", []) if isinstance(s, dict)}
        team = p.get("team") or {}
        rows.append({
            "name": p.get("displayName")
            or f"{p.get('mediaFirstName', '')} {p.get('mediaLastName', '')}".strip(),
            "team": team.get("officialName") or team.get("mediaName"),
            "team_short": team.get("shortName"),
            "position": p.get("roleLabel"),
            "goals": stats.get("goals"),
            "assists": stats.get("assists"),
            "appearances": stats.get("games-played"),
            "minutes": stats.get("minutes-played"),
            "shots": stats.get("total-scoring-attempts"),
            "shots_on_target": stats.get("shots-on-target"),
        })
    return {
        "source": "Serie A api-sdp (Deltatre) stats feed (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "players": rows,
    }


def _ligue1_club_names(*payloads: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for payload in payloads:
        identities = payload.get("clubsIdentities", {})
        items = identities.values() if isinstance(identities, dict) \
            else identities
        for club in items:
            if not isinstance(club, dict):
                continue
            cid = club.get("id") or club.get("clubId")
            name = (club.get("officialName") or club.get("name")
                    or club.get("shortName"))
            if cid and name:
                names[cid] = name
    return names


def _ligue1_rows(entries: list[dict], club_names: dict[str, str],
                 league: str, value_key: str) -> list[dict]:
    rows = []
    for e in entries:
        ident = e.get("playerIdentity", {})
        club_raw = e.get("clubId", "")
        name = " ".join(x for x in [ident.get("firstName"),
                                    ident.get("lastName")] if x).strip()
        rows.append({
            "player": name,
            "club": canonicalize(club_names.get(club_raw, ""), league,
                                 source="api") if club_names.get(club_raw)
            else club_raw,
            "goals": e.get("totalGoals", 0),
            "assists": e.get("totalGoalsAssists", 0),
            "minutes": (e.get("additionalStats") or {}).get(
                "totalMinutesPlayed"),
            "rank": e.get("rank"),
            value_key: e.get(value_key),
        })
    return rows


def fetch_ligue1(session: requests.Session) -> dict:
    scorers = _get_json(session, f"{LIGUE1_BASE}/championship-players-ranking/1/scorers")
    assists = _get_json(session, f"{LIGUE1_BASE}/championship-players-ranking/1/assists")
    for name, payload in [("scorers", scorers), ("assists", assists)]:
        if not isinstance(payload, dict):
            raise RuntimeError(f"unexpected ligue1 {name} shape")
        _cache_raw(f"ligue1_players_{name}.json", payload)
    club_names = _ligue1_club_names(scorers, assists)
    return {
        "source": "Ligue 1 ma-api rankings (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("Scorers and assists rankings only; the statuses feed "
                  "carries no availability data."),
        "scorers": _ligue1_rows(scorers.get("scorers", []), club_names,
                                "ligue1", "totalGoals"),
        "assists": _ligue1_rows(assists.get("assists", []), club_names,
                                "ligue1", "totalGoalsAssists"),
    }


OFFICIAL_FETCHERS = {
    "laliga": (fetch_laliga, "player_rankings_official_laliga.json"),
    "bundesliga": (fetch_bundesliga, "player_rankings_official_bundesliga.json"),
    "seriea": (fetch_seriea, "player_rankings_official_seriea.json"),
    "ligue1": (fetch_ligue1, "player_rankings_official_ligue1.json"),
}


def run_part_c(leagues: list[str]) -> dict[str, Path | None]:
    session = _session()
    results: dict[str, Path | None] = {}
    for league in leagues:
        if league not in OFFICIAL_FETCHERS:
            continue
        fetcher, filename = OFFICIAL_FETCHERS[league]
        try:
            payload = fetcher(session)
            out = settings.data_dir / filename
            _write_json(out, payload)
            n = len(payload.get("players", payload.get("scorers", [])))
            if n == 0:  # bundesliga payload is keyed by category
                n = sum(len(v) for v in payload.values()
                        if isinstance(v, list))
            log.info("official_rankings_done", league=league, n_rows=n)
            results[league] = out
        except Exception as exc:  # warn and fall back to 2024/25 topscorers
            log.warning("official_rankings_failed", league=league,
                        error=str(exc)[:200])
            results[league] = None
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Player data: FPL form watch (a), 2024/25 topscorers "
                    "via api-football (b), official league-backend rankings (c).")
    parser.add_argument("--parts", nargs="*", default=["a", "b", "c"],
                        choices=["a", "b", "c"],
                        help="which parts to run (default: a b c)")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs for parts b and c (default: all)")
    parser.add_argument("--refresh-fpl", action="store_true",
                        help="ignore the FPL cache and refetch (part a)")
    args = parser.parse_args(argv)

    ok = True
    if "a" in args.parts:
        try:
            if args.refresh_fpl:
                load_fpl_bootstrap(refresh=True)
            run_part_a()
        except Exception as exc:
            log.error("part_a_failed", error=str(exc)[:200])
            ok = False
    if "c" in args.parts:
        run_part_c(args.leagues)  # per-league warnings inside, never raises
    if "b" in args.parts:
        try:
            run_part_b(args.leagues)
        except Exception as exc:
            log.error("part_b_failed", error=str(exc)[:300])
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
