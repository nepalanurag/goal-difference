"""Tests for etl.ai_forecaster: horizon window, orphan pruning, newly-scored count."""
from __future__ import annotations

import pandas as pd

from etl import ai_forecaster, ledger
from etl.config import settings


def test_forecast_league_limits_to_matchweek_and_prunes_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    pd.DataFrame([
        {"fixture_id": "f1", "date": "2026-10-24", "season": "2026", "league": "pl",
         "home": "Arsenal", "away": "Chelsea", "home_goals": None, "away_goals": None, "status": "scheduled"},
        {"fixture_id": "f2", "date": "2026-12-20", "season": "2026", "league": "pl",
         "home": "Arsenal", "away": "Everton", "home_goals": None, "away_goals": None, "status": "scheduled"},
    ]).to_csv(tmp_path / "fixtures_pl.csv", index=False)

    # Pre-seed ledger with an orphaned unscored rescheduled fixture
    ledger.init_ledger("pl")
    ledger.append_predictions("pl", [{
        "fixture_date": "2026-10-20", "home": "Arsenal", "away": "Chelsea",
        "p_home_poisson": 0.5, "p_draw_poisson": 0.25, "p_away_poisson": 0.25,
        "p_home_ml": 0.5, "p_draw_ml": 0.25, "p_away_ml": 0.25,
        "p_home_ens": 0.5, "p_draw_ens": 0.25, "p_away_ens": 0.25,
        "model_version": "v0",
    }])

    fake_preds = pd.DataFrame([
        {"fixture_id": "f1", "date": "2026-10-24", "home": "Arsenal", "away": "Chelsea",
         "p_home_poisson": 0.6, "p_draw_poisson": 0.2, "p_away_poisson": 0.2,
         "p_home_ml": 0.6, "p_draw_ml": 0.2, "p_away_ml": 0.2,
         "p_home_ens": 0.6, "p_draw_ens": 0.2, "p_away_ens": 0.2,
         "xg_home": 1.5, "xg_away": 0.8, "model_version": "v1"},
        {"fixture_id": "f2", "date": "2026-12-20", "home": "Arsenal", "away": "Everton",
         "p_home_poisson": 0.7, "p_draw_poisson": 0.2, "p_away_poisson": 0.1,
         "p_home_ml": 0.7, "p_draw_ml": 0.2, "p_away_ml": 0.1,
         "p_home_ens": 0.7, "p_draw_ens": 0.2, "p_away_ens": 0.1,
         "xg_home": 1.8, "xg_away": 0.5, "model_version": "v1"},
    ])
    monkeypatch.setattr(ai_forecaster.fit, "predict_upcoming", lambda lg: fake_preds)
    n = ai_forecaster.forecast_league("pl", horizon_days=7)
    assert n == 1
    led = pd.read_csv(tmp_path / "predictions_ledger_pl.csv")
    assert list(led["fixture_date"]) == ["2026-10-24"]


def test_score_unscored_counts_only_newly_scored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    pd.DataFrame([
        {"fixture_id": "f1", "date": "2026-10-10", "season": "2026", "league": "pl",
         "home": "Arsenal", "away": "Chelsea", "home_goals": 2, "away_goals": 0, "status": "finished"},
        {"fixture_id": "f2", "date": "2026-10-17", "season": "2026", "league": "pl",
         "home": "Liverpool", "away": "Everton", "home_goals": 1, "away_goals": 1, "status": "finished"},
    ]).to_csv(tmp_path / "fixtures_pl.csv", index=False)

    ledger.init_ledger("pl")
    ledger.append_predictions("pl", [
        {"fixture_date": "2026-10-10", "home": "Arsenal", "away": "Chelsea",
         "p_home_poisson": 0.6, "p_draw_poisson": 0.2, "p_away_poisson": 0.2,
         "p_home_ml": 0.6, "p_draw_ml": 0.2, "p_away_ml": 0.2,
         "p_home_ens": 0.6, "p_draw_ens": 0.2, "p_away_ens": 0.2, "model_version": "v1"},
        {"fixture_date": "2026-10-17", "home": "Liverpool", "away": "Everton",
         "p_home_poisson": 0.5, "p_draw_poisson": 0.3, "p_away_poisson": 0.2,
         "p_home_ml": 0.5, "p_draw_ml": 0.3, "p_away_ml": 0.2,
         "p_home_ens": 0.5, "p_draw_ens": 0.3, "p_away_ens": 0.2, "model_version": "v1"},
    ])
    # First score row 1 only
    ledger.score_league("pl", pd.DataFrame([
        {"fixture_date": "2026-10-10", "home": "Arsenal", "away": "Chelsea", "result": 2},
    ]))
    # Now score_unscored must report ONLY row 2 as newly_scored
    stats = ai_forecaster.score_unscored("pl")
    assert stats["newly_scored"] == 1
