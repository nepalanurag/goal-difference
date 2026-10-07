"""UEFA competition fixtures via ESPN's hidden scoreboard API.

Free, no key. Replaces the api-football European accumulator (the free tier
blocks the current season). Day-by-day fetches: the API rejects the
hypothetical ?dates=A-B range syntax with a 400, so each day is fetched
individually with a 1s pause between requests.

Team names are ESPN display names ("Atlético Madrid", "Internazionale");
they are canonicalized via team_names.canonicalize_espn so European
history joins cleanly against league fixtures. Non-top-5 clubs keep their
ESPN name (they simply never match a league team in load_european).
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.request
from datetime import date, timedelta

from .logging_setup import get_logger
from .team_names import canonicalize_espn

log = get_logger(__name__)

ESPN_SLUGS = {
    "UCL": "uefa.champions",
    "UEL": "uefa.europa",
    "UECL": "uefa.europa.conf",
}

# Domestic league slugs for real fixture data (replaces schedule reconstruction).
LEAGUE_SLUGS = {
    "laliga": "esp.1",
    "bundesliga": "ger.1",
    "seriea": "ita.1",
    "ligue1": "fra.1",
}

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_FINISHED_EXACT = {"STATUS_FULL_TIME"}


def _is_finished(status_name: str) -> bool:
    name = (status_name or "").upper()
    return name in _FINISHED_EXACT or name.startswith("STATUS_FINAL")


def _get_json(url: str, timeout: int = 30) -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except Exception as exc:
        log.warning("espn_request_failed", url=url, error=str(exc)[:160])
        return None


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_event(event: dict, competition: str) -> dict | None:
    try:
        comps = event["competitions"][0]
        competitors = comps["competitors"]
        home = next(c for c in competitors if c.get("homeAway") == "home")
        away = next(c for c in competitors if c.get("homeAway") == "away")
    except (KeyError, IndexError, StopIteration):
        log.warning("espn_event_parse_failed", event_id=event.get("id"))
        return None
    status_name = comps.get("status", {}).get("type", {}).get("name", "")
    finished = _is_finished(status_name)
    return {
        "fixture_id": f"espn-{event.get('id')}",
        "date": (event.get("date") or "")[:10],
        "competition": competition,
        "home": canonicalize_espn(home["team"]["displayName"]),
        "away": canonicalize_espn(away["team"]["displayName"]),
        "home_goals": _to_int(home.get("score")) if finished else None,
        "away_goals": _to_int(away.get("score")) if finished else None,
        "status": "finished" if finished else "scheduled",
    }


def fetch_espn_uefa(start_date: str, end_date: str) -> list[dict]:
    """Fetch UEFA fixtures for every day in [start_date, end_date].

    Dates are YYYY-MM-DD strings. Returns one dict per fixture with keys:
    fixture_id ("espn-<event id>"), date, competition ("UCL"/"UEL"/"UECL"),
    home, away (canonical team names), home_goals, away_goals (int or None),
    status ("finished"/"scheduled"). HTTP failures log a warning and the
    day/competition is skipped.
    """
    rows: list[dict] = []
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    day = start
    while day <= end:
        stamp = day.strftime("%Y%m%d")
        for comp, slug in ESPN_SLUGS.items():
            data = _get_json(f"{_BASE}/{slug}/scoreboard?dates={stamp}")
            time.sleep(1)
            if not data:
                continue
            for event in data.get("events", []):
                row = _parse_event(event, comp)
                if row and row["date"]:
                    rows.append(row)
        day += timedelta(days=1)
    log.info("espn_uefa_fetched", start=start_date, end=end_date, n=len(rows))
    return rows


def fetch_espn_league(league: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch real fixtures for a domestic league via ESPN scoreboard.

    Dates are YYYY-MM-DD strings. Returns one dict per fixture with keys:
    fixture_id ("espn-<event id>"), date, competition (league slug),
    home, away (canonical team names), home_goals, away_goals (int or None),
    status ("finished"/"scheduled"). Only fixtures where BOTH teams are in
    the league's canonical team set are returned (filters out playoff/
    cross-competition noise).
    """
    from .team_names import CANONICAL
    slug = LEAGUE_SLUGS.get(league)
    if not slug:
        raise ValueError(f"no ESPN slug for league {league}")
    known = CANONICAL.get(league, set())
    rows: list[dict] = []
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    day = start
    while day <= end:
        stamp = day.strftime("%Y%m%d")
        data = _get_json(f"{_BASE}/{slug}/scoreboard?dates={stamp}")
        time.sleep(1)
        if data:
            for event in data.get("events", []):
                row = _parse_event(event, slug)
                if row and row["date"] and row["home"] in known and row["away"] in known:
                    rows.append(row)
        day += timedelta(days=1)
    log.info("espn_league_fetched", league=league, start=start_date,
             end=end_date, n=len(rows))
    return rows
