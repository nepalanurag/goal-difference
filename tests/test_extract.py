"""Tests for etl.extract: live CSV backfill and round-robin schedule completion."""
from __future__ import annotations

import pandas as pd

from etl.extract import OUTPUT_COLS, STAT_COLS, _merge_csv_stats, _reconstruct_missing_rounds
from etl.team_names import CANONICAL


def test_merge_csv_stats_backfills_null_live_cols():
    live = pd.DataFrame([{
        "fixture_id": "pl-2026-2026-08-15-arsenal-v-chelsea",
        "date": "2026-08-15", "season": "2026", "league": "pl",
        "home": "Arsenal", "away": "Chelsea",
        "home_goals": 2, "away_goals": 1, "status": "finished",
        "provenance": "fpl_api", "api_fixture_id": 1,
        **{c: None for c in STAT_COLS},
    }], columns=OUTPUT_COLS)
    csv_df = pd.DataFrame([{
        "fixture_id": "pl-2026-2026-08-16-arsenal-v-chelsea",
        "date": "2026-08-16", "season": "2026", "league": "pl",
        "home": "Arsenal", "away": "Chelsea",
        "home_goals": 2, "away_goals": 1, "status": "finished",
        "provenance": "csv_download", "api_fixture_id": None,
        "hs": 15.0, "as_": 8.0, "hst": 6.0, "ast": 3.0,
        "hf": 10.0, "af": 12.0, "hy": 1.0, "ay": 2.0, "hr": 0.0, "ar": 0.0,
    }], columns=OUTPUT_COLS)
    merged = _merge_csv_stats(live, csv_df)
    assert merged.iloc[0]["hs"] == 15.0
    assert merged.iloc[0]["hst"] == 6.0


def test_reconstruct_missing_rounds_completes_double_round_robin():
    teams = sorted(CANONICAL["bundesliga"])[:18]
    # Seed 1 full matchday (9 matches)
    rows = []
    for i in range(0, 18, 2):
        rows.append({
            "fixture_id": f"b-{i}", "date": "2026-08-22", "season": "2026",
            "league": "bundesliga", "home": teams[i], "away": teams[i + 1],
            "home_goals": 1, "away_goals": 0, "status": "finished",
            "provenance": "espn", "api_fixture_id": None,
            **{c: None for c in STAT_COLS},
        })
    df = pd.DataFrame(rows, columns=OUTPUT_COLS)
    recon = _reconstruct_missing_rounds(df, "bundesliga", "2026")
    full = pd.concat([df, recon], ignore_index=True)
    assert len(full) == 306
    assert full.duplicated(subset=["home", "away"]).sum() == 0
    # Each reconstructed date has at most 1 fixture per team
    for _, grp in recon.groupby("date"):
        played_on_day = list(grp["home"]) + list(grp["away"])
        assert len(played_on_day) == len(set(played_on_day))


def test_uefa_filters_to_ucl_uel_and_top5_clubs(monkeypatch):
    from etl import uefa
    assert set(uefa.ESPN_SLUGS) == {"UCL", "UEL"}

    fake_events = {
        "uefa.champions": [
            {"id": "1", "date": "2026-10-01T19:00Z", "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Arsenal"}, "score": "2"},
                    {"homeAway": "away", "team": {"displayName": "FC Porto"}, "score": "0"},
                ],
                "status": {"type": {"name": "STATUS_FULL_TIME"}},
            }]},
            {"id": "2", "date": "2026-10-01T19:00Z", "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "AEK Athens"}, "score": "1"},
                    {"homeAway": "away", "team": {"displayName": "LASK Linz"}, "score": "0"},
                ],
                "status": {"type": {"name": "STATUS_FULL_TIME"}},
            }]},
        ],
        "uefa.europa": [],
    }
    monkeypatch.setattr(uefa, "_get_json", lambda url, timeout=30: {
        "events": fake_events["uefa.champions" if "champions" in url else "uefa.europa"]
    })
    rows = uefa.fetch_espn_uefa("2026-10-01", "2026-10-02", top5_only=True)
    assert len(rows) == 1
    assert rows[0]["home"] == "Arsenal" and rows[0]["competition"] == "UCL"
