"""Head-to-head records from all loaded seasons per league.

Reads data/fixtures_{league}.csv, keeps finished fixtures, and writes
data/h2h_{league}.json. Every unordered pairing is stored under both
directed keys ("A vs B" and "B vs A") so lookups need no key flipping:

  "Arsenal vs Chelsea": {
      "last5":   [{"date", "venue", "home", "away", "home_goals",
                   "away_goals"}, ...],   # most recent first
      "alltime": {"w": 12, "d": 8, "l": 9}  # from A's perspective
  }

venue is "H"/"A"/"N" from the first-named team's perspective. Only
finished fixtures are used; scheduled ones are ignored.

Usage:
    python -m etl.h2h [--leagues pl laliga bundesliga seriea ligue1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

LAST_N = 5


def _directed_record(team: str, meetings: pd.DataFrame) -> dict:
    """last5 + alltime for one directed pairing, from team's perspective."""
    recent = meetings.sort_values("date", ascending=False).head(LAST_N)
    last5 = []
    for row in recent.itertuples():
        if row.home == team:
            venue = "H"
        elif row.away == team:
            venue = "A"
        else:  # cannot happen for league fixtures; kept for the contract
            venue = "N"
        last5.append({
            "date": str(row.date),
            "venue": venue,
            "home": row.home,
            "away": row.away,
            "home_goals": int(row.home_goals),
            "away_goals": int(row.away_goals),
        })

    w = d = l = 0
    for row in meetings.itertuples():
        if row.home_goals == row.away_goals:
            d += 1
        elif (row.home == team and row.home_goals > row.away_goals) or \
             (row.away == team and row.away_goals > row.home_goals):
            w += 1
        else:
            l += 1
    return {"last5": last5, "alltime": {"w": w, "d": d, "l": l}}


def build_h2h(league: str,
              fixtures_path: Path | None = None,
              out_path: Path | None = None) -> dict:
    """Build the head-to-head dict for one league and write it as JSON."""
    fixtures_path = fixtures_path or settings.data_dir / f"fixtures_{league}.csv"
    out_path = out_path or settings.data_dir / f"h2h_{league}.json"
    if league not in settings.leagues:
        raise ValueError(f"unknown league: {league}")
    if not fixtures_path.exists():
        raise FileNotFoundError(f"fixtures file not found: {fixtures_path}")

    df = pd.read_csv(fixtures_path, dtype={"date": str})
    finished = df[df["status"] == "finished"].copy()
    if finished.empty:
        log.warning("h2h_no_finished_fixtures", league=league)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("{}")
        return {}

    finished["pair"] = finished.apply(
        lambda r: tuple(sorted((r["home"], r["away"]))), axis=1)

    h2h: dict[str, dict] = {}
    for (team_a, team_b), meetings in finished.groupby("pair"):
        h2h[f"{team_a} vs {team_b}"] = _directed_record(team_a, meetings)
        h2h[f"{team_b} vs {team_a}"] = _directed_record(team_b, meetings)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(h2h, indent=2))
    log.info("h2h_written", league=league, pairings=len(h2h),
             meetings=int(len(finished)), path=str(out_path))
    return h2h


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leagues", nargs="*", default=settings.league_order,
                        help="league slugs (default: all)")
    args = parser.parse_args(argv)

    for league in args.leagues:
        try:
            build_h2h(league)
        except (FileNotFoundError, ValueError) as exc:
            log.error("h2h_error", league=league, error=str(exc))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
