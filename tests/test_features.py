"""Tests for etl.features: shift(1) no-leakage and feature sanity."""
from __future__ import annotations

import pandas as pd

from etl import features
from etl.features import ELO_START, TeamHistory, elo_update, haversine_km


def test_haversine_london_manchester():
    km = haversine_km((51.5074, -0.1278), (53.4808, -2.2426))
    assert 250 < km < 350


def test_team_history_shift1_no_leakage():
    th = TeamHistory()
    assert th.features() == {}
    th.add("2023-08-01", "H", 2, 0, {}, "B")
    f = th.features()
    assert f["w5"] == 1 and f["gf5"] == 2 and f["ga5"] == 0
    assert f["ppg"] == 3.0
    # The match just added must NOT appear twice.
    assert f["gf_pg"] == 2.0


def test_build_features_uses_only_past(tmp_path, monkeypatch):
    """A team's feature row for fixture N uses only fixtures before N."""
    from etl import config as cfg
    rows = [
        # Team A beats B 3-0, then A loses to B 0-1.
        {"fixture_id": "f1", "date": "2023-08-01", "season": "2023",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 3, "away_goals": 0, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
        {"fixture_id": "f2", "date": "2023-08-08", "season": "2023",
         "league": "pl", "home": "Chelsea", "away": "Arsenal",
         "home_goals": 1, "away_goals": 0, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
    ]
    for c in ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]:
        for r in rows:
            r[c] = None
    df = pd.DataFrame(rows)
    fx_path = tmp_path / "fixtures_pl.csv"
    df.to_csv(fx_path, index=False)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    feats, meta = features.build_features("pl")
    assert len(feats) == 2
    # Fixture 2: Arsenal's features must reflect ONLY the 3-0 win (shift(1)).
    r2 = feats[feats.fixture_id == "f2"].iloc[0]
    assert r2["a_gf_pg"] == 3.0  # Arsenal away: 3 goals in 1 prior game
    assert r2["a_ga_pg"] == 0.0
    assert r2["a_w5"] == 1
    # Fixture 1: no history -> neutral imputation, not NaN.
    r1 = feats[feats.fixture_id == "f1"].iloc[0]
    assert r1.filter(like="h_").notna().all()
    assert meta["feature_logic_version"] == features.feature_logic_version()
    assert len(meta["feature_logic_version"]) == 12


def test_elo_is_point_in_time(tmp_path, monkeypatch):
    """A fixture's Elo must equal the chronological rating after only the
    earlier fixtures, never including its own result."""
    from etl import config as cfg
    rows = [
        {"fixture_id": "f1", "date": "2023-08-01", "season": "2023",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 3, "away_goals": 0, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
        {"fixture_id": "f2", "date": "2023-08-08", "season": "2023",
         "league": "pl", "home": "Chelsea", "away": "Arsenal",
         "home_goals": 1, "away_goals": 0, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
        {"fixture_id": "f3", "date": "2023-08-15", "season": "2023",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 2, "away_goals": 0, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
    ]
    for c in ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]:
        for r in rows:
            r[c] = None
    df = pd.DataFrame(rows)
    fx_path = tmp_path / "fixtures_pl.csv"
    df.to_csv(fx_path, index=False)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    feats, _ = features.build_features("pl")
    # Chronological ratings after f1 and f2 only (same update rule the
    # pipeline uses).
    ar1, ch1 = elo_update(ELO_START, ELO_START, 3, 0)
    ch2, ar2 = elo_update(ch1, ar1, 1, 0)
    r3 = feats[feats.fixture_id == "f3"].iloc[0]
    assert r3["h_elo"] == ar2  # Arsenal: after f1 win and f2 loss only
    assert r3["a_elo"] == ch2  # Chelsea: after f1 loss and f2 win only
    assert r3["elo_diff"] == ar2 - ch2
    # f3's own 2-0 would move the ratings further; the row must not
    # contain that.
    ar3, ch3 = elo_update(ar2, ch2, 2, 0)
    assert r3["h_elo"] != ar3
    assert r3["a_elo"] != ch3
    # f2's row likewise only sees f1.
    r2 = feats[feats.fixture_id == "f2"].iloc[0]
    assert r2["h_elo"] == ch1 and r2["a_elo"] == ar1
