"""Tests for etl.h2h: directed pairings, last-5 ordering, all-time W/D/L."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etl import h2h
from tests.helpers import ALL_COLS, STAT_COLS

A, B, C = "Arsenal", "Chelsea", "Liverpool"

# Six finished Arsenal-Chelsea meetings, oldest first. From Arsenal's view:
# H 2-0 W, A 1-1 D, H 0-1 L, A 3-1 W, H 1-1 D, A 2-2 D
MEETINGS = [
    ("2023-10-21", A, B, 2, 0),
    ("2024-04-23", B, A, 1, 1),
    ("2024-11-10", A, B, 0, 1),
    ("2025-03-16", B, A, 1, 3),
    ("2025-08-30", A, B, 1, 1),
    ("2025-12-20", B, A, 2, 2),
]


def _frame() -> pd.DataFrame:
    rows = []
    for i, (date, home, away, hg, ag) in enumerate(MEETINGS):
        rows.append({
            "fixture_id": f"m-{i}", "date": date, "season": "2025",
            "league": "pl", "home": home, "away": away,
            "home_goals": hg, "away_goals": ag, "status": "finished",
            "provenance": "csv_cached", "api_fixture_id": None,
            **{c: None for c in STAT_COLS},
        })
    # a scheduled meeting must be ignored
    rows.append({
        "fixture_id": "m-x", "date": "2026-01-15", "season": "2026",
        "league": "pl", "home": A, "away": C,
        "home_goals": None, "away_goals": None, "status": "scheduled",
        "provenance": "fpl_api", "api_fixture_id": None,
        **{c: None for c in STAT_COLS},
    })
    return pd.DataFrame(rows, columns=ALL_COLS)


def _build(tmp: Path) -> dict:
    fx = tmp / "fixtures_pl.csv"
    out = tmp / "h2h_pl.json"
    _frame().to_csv(fx, index=False)
    return h2h.build_h2h("pl", fixtures_path=fx, out_path=out)


def test_directed_keys_and_last5_order(tmp_path):
    data = _build(tmp_path)
    key = f"{A} vs {B}"
    assert key in data
    last5 = data[key]["last5"]
    assert len(last5) == 5
    # most recent first
    assert [m["date"] for m in last5] == [
        "2025-12-20", "2025-08-30", "2025-03-16", "2024-11-10", "2024-04-23"]
    # venue from Arsenal's perspective: away, home, away, home, away
    assert [m["venue"] for m in last5] == ["A", "H", "A", "H", "A"]
    first = last5[0]
    assert (first["home"], first["away"]) == (B, A)
    assert (first["home_goals"], first["away_goals"]) == (2, 2)


def test_alltime_from_first_named_team(tmp_path):
    data = _build(tmp_path)
    # Arsenal: W (2-0 H, 3-1 A), D (1-1 A, 1-1 H, 2-2 A), L (0-1 H)
    assert data[f"{A} vs {B}"]["alltime"] == {"w": 2, "d": 3, "l": 1}
    # flipped key: Chelsea's perspective mirrors it
    assert data[f"{B} vs {A}"]["alltime"] == {"w": 1, "d": 3, "l": 2}
    assert data[f"{B} vs {A}"]["last5"][0]["venue"] == "H"


def test_scheduled_fixtures_excluded(tmp_path):
    data = _build(tmp_path)
    assert f"{A} vs {C}" not in data
    assert f"{C} vs {A}" not in data


def test_json_file_matches_return(tmp_path):
    data = _build(tmp_path)
    on_disk = json.loads((tmp_path / "h2h_pl.json").read_text())
    assert on_disk == data


def test_main_cli(tmp_path, monkeypatch):
    from etl.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _frame().to_csv(tmp_path / "fixtures_pl.csv", index=False)
    assert h2h.main(["--leagues", "pl"]) == 0
    assert (tmp_path / "h2h_pl.json").exists()
    assert h2h.main(["--leagues", "nope"]) == 1
