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


def test_injury_drag_monotonicity_and_no_leakage(tmp_path, monkeypatch):
    """Player absences must strictly reduce effective Elo in predict mode,
    and historical finished matches must strictly receive 0 drag (no leakage)."""
    import json
    from etl import config as cfg

    # Fixtures: 1 finished match + 1 upcoming scheduled match
    rows = [
        {"fixture_id": "f_fin", "date": "2026-08-10", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 2, "away_goals": 1, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None},
        {"fixture_id": "f_sched", "date": "2026-10-20", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": None, "away_goals": None, "status": "scheduled",
         "provenance": "fpl_fixtures", "api_fixture_id": None},
    ]
    for c in ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]:
        for r in rows:
            r[c] = None
    df = pd.DataFrame(rows)
    df.to_csv(tmp_path / "fixtures_pl.csv", index=False)

    # Write team news with Arsenal heavily injured (drag_att=0.15, drag_def=0.10)
    # and Chelsea fully fit (0.0 drag)
    news_payload = {
        "league": "pl",
        "teams": {
            "Arsenal": {"drag_att": 0.15, "drag_def": 0.10, "key_absences": 2},
            "Chelsea": {"drag_att": 0.0, "drag_def": 0.0, "key_absences": 0},
        }
    }
    (tmp_path / "team_news_pl.json").write_text(json.dumps(news_payload))
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    # 1. Train mode: historical finished match must have ZERO injury drag (no leakage)
    feats_train, _ = features.build_features("pl", mode="train")
    assert len(feats_train) == 1
    r_train = feats_train.iloc[0]
    assert r_train["h_injury_drag_att"] == 0.0
    assert r_train["h_injury_drag_def"] == 0.0
    assert r_train["injury_drag_diff"] == 0.0
    assert r_train["effective_elo_diff"] == r_train["elo_diff"]

    # 2. Predict mode: scheduled match must reflect injury drag and penalize effective Elo
    feats_pred, _ = features.build_features("pl", mode="predict")
    assert len(feats_pred) == 1
    r_pred = feats_pred.iloc[0]
    assert r_pred["h_injury_drag_att"] == 0.15
    assert r_pred["h_injury_drag_def"] == 0.10
    assert r_pred["a_injury_drag_att"] == 0.0
    assert r_pred["a_injury_drag_def"] == 0.0
    # Net drag diff: (0.15 + 0.10) - 0.0 = 0.25 > 0
    assert r_pred["injury_drag_diff"] == 0.25
    # Effective Elo must be strictly penalized relative to base Elo difference:
    # effective_elo_diff = elo_diff - 150.0 * 0.25 = elo_diff - 37.5
    assert r_pred["effective_elo_diff"] < r_pred["elo_diff"]
    assert abs(r_pred["effective_elo_diff"] - (r_pred["elo_diff"] - 37.5)) < 1e-6


def test_load_injury_drags_fallback(tmp_path, monkeypatch):
    """Unknown or missing league must return empty dict gracefully."""
    from etl import config as cfg
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    res = features.load_injury_drags("unknown_league")
    assert res == {}


def test_compute_rest_days_accounts_for_european_midweek():
    """European competition match 3 days prior must be preferred over 7-day domestic match."""
    from etl.features import compute_rest_days

    last_date = {"Arsenal": "2026-10-17"}  # Saturday domestic game
    euro = {"Arsenal": [{"date": "2026-10-21", "pts": 3, "gf": 2, "ga": 0}]}  # Wednesday UCL

    # Match on Saturday 2026-10-24
    rest = compute_rest_days("Arsenal", "2026-10-24", last_date, euro)
    assert rest == 3, f"Expected 3 days turnaround from UCL, got {rest}"


def test_compute_rest_days_bounds_and_summer_break():
    """Summer break (>30d) normalizes to fully rested 14d, same-day/negative bounds to 1d."""
    from etl.features import compute_rest_days

    # Summer break (80 days)
    last_date = {"Man City": "2026-05-19"}
    rest = compute_rest_days("Man City", "2026-08-15", last_date, {})
    assert rest == 14, f"Expected 14d normalized summer break, got {rest}"

    # Same day or out of order fixture
    last_date = {"Man City": "2026-10-20"}
    rest = compute_rest_days("Man City", "2026-10-20", last_date, {})
    assert rest == 7, "Same day should ignore same-day as prior match and fallback"

    # 1 day rest (back to back)
    last_date = {"Man City": "2026-10-19"}
    rest = compute_rest_days("Man City", "2026-10-20", last_date, {})
    assert rest == 1


def test_predict_mode_advances_rest_days_calendar(tmp_path, monkeypatch):
    """Multiple sequential scheduled fixtures must not saturate at 30 days."""
    import pandas as pd
    from etl import config as cfg
    from etl.features import build_features

    rows = [
        # Finished match on Oct 10
        {"fixture_id": "f_fin", "date": "2026-10-10", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 2, "away_goals": 1, "status": "finished",
         "provenance": "csv", "api_fixture_id": None},
        # Scheduled match 1 on Oct 17 (7 days later)
        {"fixture_id": "f_sch1", "date": "2026-10-17", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Everton",
         "home_goals": None, "away_goals": None, "status": "scheduled",
         "provenance": "fpl", "api_fixture_id": None},
        # Scheduled match 2 on Oct 24 (7 days later)
        {"fixture_id": "f_sch2", "date": "2026-10-24", "season": "2026",
         "league": "pl", "home": "Liverpool", "away": "Arsenal",
         "home_goals": None, "away_goals": None, "status": "scheduled",
         "provenance": "fpl", "api_fixture_id": None},
        # Scheduled match 3 on Nov 07 (14 days later, international break)
        {"fixture_id": "f_sch3", "date": "2026-11-07", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Tottenham",
         "home_goals": None, "away_goals": None, "status": "scheduled",
         "provenance": "fpl", "api_fixture_id": None},
    ]
    for c in ["hs", "as_", "hst", "ast", "hf", "af", "hy", "ay", "hr", "ar"]:
        for r in rows:
            r[c] = None
    df = pd.DataFrame(rows)
    df.to_csv(tmp_path / "fixtures_pl.csv", index=False)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)

    feats_pred, _ = build_features("pl", mode="predict")
    assert len(feats_pred) == 3

    r1 = feats_pred[feats_pred.fixture_id == "f_sch1"].iloc[0]
    r2 = feats_pred[feats_pred.fixture_id == "f_sch2"].iloc[0]
    r3 = feats_pred[feats_pred.fixture_id == "f_sch3"].iloc[0]

    assert r1["h_rest_days"] == 7
    assert r2["a_rest_days"] == 7, f"Expected 7 days, got {r2['a_rest_days']} (30d saturation bug!)"
    assert r3["h_rest_days"] == 14, f"Expected 14 days, got {r3['h_rest_days']}"


def test_load_european_skips_scheduled_fixtures(tmp_path, monkeypatch):
    import json
    from etl import config as cfg
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    rows = [
        {"fixture_id": "e1", "date": "2026-09-09", "competition": "UCL",
         "home": "Arsenal", "away": "Napoli", "home_goals": 2, "away_goals": 0, "status": "finished"},
        {"fixture_id": "e2", "date": "2026-10-20", "competition": "UCL",
         "home": "Arsenal", "away": "Roma", "home_goals": None, "away_goals": None, "status": "scheduled"},
    ]
    (tmp_path / "european_fixtures.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    euro = features.load_european()
    assert len(euro["Arsenal"]) == 1
    assert euro["Arsenal"][0]["pts"] == 3
    assert "Roma" not in euro


def test_predict_mode_imputes_missing_stats_with_league_mean(tmp_path, monkeypatch):
    from etl import config as cfg
    rows = [
        {"fixture_id": "f1", "date": "2026-09-01", "season": "2026",
         "league": "pl", "home": "Arsenal", "away": "Chelsea",
         "home_goals": 2, "away_goals": 1, "status": "finished",
         "provenance": "csv_download", "api_fixture_id": None,
         "hs": 14.0, "as_": 10.0, "hst": 6.0, "ast": 4.0,
         "hf": 9.0, "af": 11.0, "hy": 1.0, "ay": 2.0, "hr": 0.0, "ar": 0.0},
        {"fixture_id": "f2", "date": "2026-09-10", "season": "2026",
         "league": "pl", "home": "Coventry City", "away": "Arsenal",
         "home_goals": None, "away_goals": None, "status": "scheduled",
         "provenance": "fpl_api", "api_fixture_id": None,
         "hs": None, "as_": None, "hst": None, "ast": None,
         "hf": None, "af": None, "hy": None, "ay": None, "hr": None, "ar": None},
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "fixtures_pl.csv", index=False)
    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cfg.settings, "raw_dir", tmp_path)
    pred_df, _ = features.build_features("pl", mode="predict")
    assert len(pred_df) == 1
    assert pred_df.iloc[0]["h_shots_pg"] == 12.0  # mean of Arsenal (14) and Chelsea (10)
    assert pred_df.iloc[0]["h_fouls_pg"] == 10.0  # mean of Arsenal (9) and Chelsea (11)


def test_load_devigged_odds_uses_canonical_csv_aliases(tmp_path, monkeypatch):
    from etl import config as cfg
    csv_content = (
        "Date,HomeTeam,AwayTeam,B365CH,B365CD,B365CA,B365H,B365D,B365A\n"
        "16/08/2024,Ipswich,Chelsea,3.5,3.6,2.0,3.4,3.5,2.1\n"
    )
    (tmp_path / "csv_pl_2024.csv").write_text(csv_content)
    # Pre-2019 archive CSV without closing B365C columns
    csv_old = (
        "Date,HomeTeam,AwayTeam,B365H,B365D,B365A\n"
        "10/08/2015,Arsenal,Chelsea,2.1,3.4,3.5\n"
    )
    (tmp_path / "csv_pl_2015.csv").write_text(csv_old)
    monkeypatch.setattr(cfg.settings, "raw_dir", tmp_path)
    odds = features.load_devigged_odds("pl")
    assert ("Ipswich Town", "Chelsea", "2024-08-16") in odds
    assert ("Arsenal", "Chelsea", "2015-08-10") in odds


def test_h2h_metrics_before_and_squad_features_no_leakage():
    idx = {
        "Arsenal vs Chelsea": [
            {"date": "2020-01-01", "w": 1, "d": 0, "at_home": True},
            {"date": "2021-01-01", "w": 0, "d": 0, "at_home": False},
            {"date": "2026-01-01", "w": 0, "d": 1, "at_home": True},
        ]
    }
    m = features.h2h_metrics_before(idx, "Arsenal", "Chelsea", "2025-01-01")
    assert m["h2h_meetings"] == 2.0
    assert m["h2h_edge"] == 0.5
    assert m["h2h_venue_edge"] == 1.0  # won only prior home meeting

    hist = [
        {"date": "2026-09-01", "espn_id": "1", "player_ga": {"P1": 2, "P2": 1}, "saves": 3, "shots_faced": 4},
        {"date": "2026-09-10", "espn_id": "2", "player_ga": {"P1": 5}, "saves": 1, "shots_faced": 5},
    ]
    sq = features._squad_features_before(hist, "2026-09-10")
    assert sq["squad_top3_ga_l5"] == 3.0  # must exclude Sep 10 match!
    assert abs(sq["gk_save_pct_l5"] - 0.75) < 1e-9


