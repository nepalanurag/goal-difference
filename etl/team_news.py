"""Team news / player availability per league.

Premier League: from the FPL API (bootstrap-static, same payload as
etl.players part (a)): status flags, chance_of_playing_this_round /
chance_of_playing_next_round and the news text. Key absences = regular
starters (top-11 by minutes for their team) flagged out or doubtful.

Other leagues: no free source carries a current-season injury feed
(verified: api-football blocks the current season, the Ligue 1 statuses
feed is empty, the LaLiga player endpoint has no injury fields, and the
Bundesliga Firebase match nodes carry only timestamps and team ids with
no lineup or player data), so each of them gets an honestly labeled
fallback. An absence is NEVER labeled an injury or a suspension.

Inputs:
    data/raw/fpl_bootstrap_players.json (refetched if stale)

Outputs: data/team_news_{pl,laliga,bundesliga,seriea,ligue1}.json, each
carrying its source label.

Usage:
    python -m etl.team_news
    python -m etl.team_news --leagues pl bundesliga
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .logging_setup import get_logger
from .players import load_fpl_bootstrap
from .team_names import canonicalize

log = get_logger(__name__)

SEASON_LABEL = "2026/27"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    log.info("wrote_json", path=str(path))


# ---------------------------------------------------------------------------
# Premier League: FPL injury / availability flags
# ---------------------------------------------------------------------------

def _flagged(el: dict) -> str | None:
    """Return 'out' / 'doubtful' / None for one FPL element."""
    status = el.get("status")
    this_round = el.get("chance_of_playing_this_round")
    next_round = el.get("chance_of_playing_next_round")
    if status in ("i", "s", "u") or this_round == 0:
        return "out"
    if status == "d" or (this_round is not None and this_round < 100) \
            or (next_round is not None and next_round < 100):
        return "doubtful"
    return None


def build_team_news_pl(bootstrap: dict) -> dict:
    teams = {t["id"]: t["name"] for t in bootstrap.get("teams", [])}
    elements = bootstrap.get("elements", [])

    by_team: dict[str, list[dict]] = {}
    for el in elements:
        team = canonicalize(teams.get(el.get("team"), ""), "pl",
                            source="fpl")
        by_team.setdefault(team, []).append(el)

    team_news: dict[str, dict] = {}
    total_out = total_doubtful = 0
    for team in sorted(by_team):
        squad = by_team[team]
        # Regular starters: top-11 by minutes this season.
        starters = {el["id"] for el in
                    sorted(squad, key=lambda e: e.get("minutes") or 0,
                           reverse=True)[:11]}
        out, doubtful = [], []
        for el in squad:
            flag = _flagged(el)
            if flag is None:
                continue
            name = f"{el.get('first_name', '')} {el.get('second_name', '')}".strip()
            entry = {
                "player": name,
                "status": el.get("status"),
                "chance_this_round": el.get("chance_of_playing_this_round"),
                "chance_next_round": el.get("chance_of_playing_next_round"),
                "news": (el.get("news") or "").strip(),
                "regular_starter": el.get("id") in starters,
            }
            (out if flag == "out" else doubtful).append(entry)
        key_absences = sum(1 for e in out + doubtful if e["regular_starter"])
        total_out += len(out)
        total_doubtful += len(doubtful)
        team_news[team] = {
            "out": out,
            "doubtful": doubtful,
            "key_absences": key_absences,
        }

    return {
        "league": "pl",
        "source": "FPL API (unofficial)",
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "notes": ("Injury and suspension flags come from FPL status, "
                  "chance-of-playing and news fields. key_absences counts "
                  "flagged players who are in their team's top-11 by "
                  "minutes this season."),
        "teams": team_news,
    }


def run_pl() -> Path:
    bootstrap = load_fpl_bootstrap()
    payload = build_team_news_pl(bootstrap)
    out = settings.data_dir / "team_news_pl.json"
    _write_json(out, payload)
    n_teams = len(payload["teams"])
    n_key = sum(t["key_absences"] for t in payload["teams"].values())
    log.info("team_news_pl_done", teams=n_teams, key_absences=n_key)
    return out


# ---------------------------------------------------------------------------
# Leagues with no published availability data
# ---------------------------------------------------------------------------

_FALLBACK_SOURCES = {
    "bundesliga": "bundesliga official Firebase",
    "laliga": "LaLiga apim public-service API (unofficial)",
    "seriea": "Serie A api-sdp (Deltatre) stats feed (unofficial)",
    "ligue1": "Ligue 1 ma-api (unofficial)",
}


def build_team_news_fallback(league: str) -> dict:
    return {
        "league": league,
        "source": _FALLBACK_SOURCES[league],
        "season_label": SEASON_LABEL,
        "fetched_at": _now_iso(),
        "availability": ("no current-season availability data published "
                         "by the league backend"),
        "teams": {},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Team news / availability: FPL flags for the PL, "
                    "lineup-based absence detection elsewhere, honestly "
                    "labeled.")
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs (default: all)")
    args = parser.parse_args(argv)

    ok = True
    for league in args.leagues:
        try:
            if league == "pl":
                run_pl()
            elif league in _FALLBACK_SOURCES:
                payload = build_team_news_fallback(league)
                _write_json(settings.data_dir / f"team_news_{league}.json",
                            payload)
                log.info("team_news_fallback", league=league)
            else:
                raise ValueError(f"unknown league: {league}")
        except Exception as exc:
            log.error("team_news_failed", league=league,
                      error=str(exc)[:200])
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
