"""Shared fixtures for the ETL tests: synthetic fixture frames."""
from __future__ import annotations

import pandas as pd

from etl.team_names import CANONICAL

STAT_COLS = ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]
ALL_COLS = (
    ["fixture_id", "date", "season", "league", "home", "away",
     "home_goals", "away_goals", "status", "provenance", "api_fixture_id"]
    + STAT_COLS
)


def make_season_df(league: str, season: str, start: str = "2023-08-11") -> pd.DataFrame:
    """A full valid double round-robin for the league's first n_teams teams.

    n teams -> n*(n-1) finished fixtures with non-decreasing dates, so the
    finished-count check (380 / 306) passes exactly.
    """
    from etl.config import settings

    n = settings.leagues[league]["n_teams"]
    teams = sorted(CANONICAL[league])[:n]
    order = list(range(n))
    rounds: list[list[tuple[str, str]]] = []
    for _ in range(n - 1):
        rounds.append([(teams[order[i]], teams[order[n - 1 - i]])
                       for i in range(n // 2)])
        order = [order[0]] + [order[-1]] + order[1:-1]
    rounds += [[(b, a) for a, b in rd] for rd in rounds]  # second leg

    base = pd.Timestamp(start)
    rows, k = [], 0
    for ri, rd in enumerate(rounds):
        day = (base + pd.Timedelta(days=7 * ri)).date().isoformat()
        for home, away in rd:
            hi, ai = teams.index(home), teams.index(away)
            rows.append({
                "fixture_id": f"{league}-{season}-{k:04d}",
                "date": day, "season": season, "league": league,
                "home": home, "away": away,
                "home_goals": (hi + ai) % 4, "away_goals": (hi * 2 + ai) % 3,
                "status": "finished", "provenance": "csv_cached",
                "api_fixture_id": None,
                **{c: None for c in STAT_COLS},
            })
            k += 1
    return pd.DataFrame(rows, columns=ALL_COLS)


def tiny_frame(league: str = "pl", season: str = "2025") -> pd.DataFrame:
    """A minimal 2-fixture frame in a non-completed season (count check skipped)."""
    teams = sorted(CANONICAL[league])[:4]
    rows = [
        {"fixture_id": "x-1", "date": "2025-08-16", "season": season,
         "league": league, "home": teams[0], "away": teams[1],
         "home_goals": 2, "away_goals": 1, "status": "finished",
         "provenance": "csv_cached", "api_fixture_id": None},
        {"fixture_id": "x-2", "date": "2025-08-17", "season": season,
         "league": league, "home": teams[2], "away": teams[3],
         "home_goals": 0, "away_goals": 0, "status": "finished",
         "provenance": "csv_cached", "api_fixture_id": None},
    ]
    for r in rows:
        r.update({c: None for c in STAT_COLS})
    return pd.DataFrame(rows, columns=ALL_COLS)
