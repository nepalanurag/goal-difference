"""Tests for etl.ledger: init, append, scoring math, calibration bands."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from etl import ledger
from etl.ledger import LEDGER_COLS, SCORE_COLS

LEAGUE = "pl"

ROWS = [
    {"fixture_date": "2026-08-15", "home": "Arsenal", "away": "Chelsea",
     "p_home_poisson": 0.60, "p_draw_poisson": 0.25, "p_away_poisson": 0.15,
     "p_home_ml": 0.50, "p_draw_ml": 0.30, "p_away_ml": 0.20,
     "p_home_ens": 0.55, "p_draw_ens": 0.25, "p_away_ens": 0.20,
     "model_version": "v1"},
    {"fixture_date": "2026-08-16", "home": "Liverpool", "away": "Everton",
     "p_home_poisson": 0.70, "p_draw_poisson": 0.20, "p_away_poisson": 0.10,
     "p_home_ml": 0.65, "p_draw_ml": 0.22, "p_away_ml": 0.13,
     "p_home_ens": 0.68, "p_draw_ens": 0.21, "p_away_ens": 0.11,
     "model_version": "v1"},
    {"fixture_date": "2026-08-17", "home": "Tottenham", "away": "West Ham",
     "p_home_poisson": 0.45, "p_draw_poisson": 0.27, "p_away_poisson": 0.28,
     "p_home_ml": 0.48, "p_draw_ml": 0.26, "p_away_ml": 0.26,
     "p_home_ens": 0.46, "p_draw_ens": 0.27, "p_away_ens": 0.27,
     "model_version": "v1"},
]

# result: 0 = away, 1 = draw, 2 = home
RESULTS = pd.DataFrame([
    {"fixture_date": "2026-08-15", "home": "Arsenal", "away": "Chelsea", "result": 2},
    {"fixture_date": "2026-08-16", "home": "Liverpool", "away": "Everton", "result": 0},
])


def _setup(tmp: Path) -> Path:
    path = tmp / "predictions_ledger_pl.csv"
    ledger.init_ledger(LEAGUE, path=path)
    ledger.append_predictions(LEAGUE, ROWS, path=path)
    return path


def test_init_creates_header_only(tmp_path):
    path = ledger.init_ledger(LEAGUE, path=tmp_path / "x.csv")
    df = pd.read_csv(path)
    assert list(df.columns) == LEDGER_COLS
    assert len(df) == 0
    # second init leaves the file untouched
    ledger.init_ledger(LEAGUE, path=path)
    assert len(pd.read_csv(path)) == 0


def test_append_requires_keys(tmp_path):
    path = tmp_path / "x.csv"
    ledger.init_ledger(LEAGUE, path=path)
    with pytest.raises(ValueError):
        ledger.append_predictions(LEAGUE, [{"home": "Arsenal"}], path=path)


def test_append_roundtrip(tmp_path):
    path = _setup(tmp_path)
    df = pd.read_csv(path)
    assert len(df) == 3
    assert list(df.columns) == LEDGER_COLS
    assert df.loc[0, "p_home_poisson"] == pytest.approx(0.60)


def test_score_logloss_math(tmp_path):
    path = _setup(tmp_path)
    scored = ledger.score_league(LEAGUE, RESULTS, path=path)

    row0 = scored.iloc[0]  # Arsenal won at home (result 2)
    assert row0["result"] == 2
    assert row0["logloss_poisson"] == pytest.approx(-math.log(0.60))
    assert row0["logloss_ml"] == pytest.approx(-math.log(0.50))
    assert row0["logloss_ens"] == pytest.approx(-math.log(0.55))
    assert row0["calibration_band"] == "0.5-0.6"  # ensemble top prob 0.55

    row1 = scored.iloc[1]  # Everton won away (result 0)
    assert row1["logloss_poisson"] == pytest.approx(-math.log(0.10))
    assert row1["logloss_ens"] == pytest.approx(-math.log(0.11))
    assert row1["calibration_band"] == "0.6-0.7"  # ensemble top prob 0.68

    # no result for row 2: scored columns stay NaN
    row2 = scored.iloc[2]
    assert pd.isna(row2["result"])
    assert pd.isna(row2["logloss_poisson"])
    assert row2["calibration_band"] == "unknown"

    # written back to disk with the new columns
    on_disk = pd.read_csv(path)
    assert all(c in on_disk.columns for c in LEDGER_COLS + SCORE_COLS)
    assert on_disk.loc[0, "logloss_ens"] == pytest.approx(-math.log(0.55))


def test_probabilities_clipped_before_logloss(tmp_path):
    path = tmp_path / "x.csv"
    ledger.init_ledger(LEAGUE, path=path)
    ledger.append_predictions(LEAGUE, [{
        "fixture_date": "2026-08-15", "home": "Arsenal", "away": "Chelsea",
        "p_home_poisson": 0.0, "p_draw_poisson": 0.5, "p_away_poisson": 0.5,
        "p_home_ml": 1.0, "p_draw_ml": 0.0, "p_away_ml": 0.0,
        "p_home_ens": 0.0, "p_draw_ens": 0.5, "p_away_ens": 0.5,
        "model_version": "v1",
    }], path=path)
    scored = ledger.score_league(
        LEAGUE,
        pd.DataFrame([{"fixture_date": "2026-08-15", "home": "Arsenal",
                       "away": "Chelsea", "result": 2}]),
        path=path)
    # p_home_poisson = 0 clips to 1e-6, not -inf
    assert scored.loc[0, "logloss_poisson"] == pytest.approx(-math.log(1e-6))
    assert math.isfinite(scored.loc[0, "logloss_poisson"])


def test_result_without_prediction_warns_not_crashes(tmp_path, caplog):
    path = _setup(tmp_path)
    extra = pd.DataFrame([{"fixture_date": "2026-09-01", "home": "Nope",
                           "away": "Nada", "result": 1}])
    scored = ledger.score_league(LEAGUE, pd.concat([RESULTS, extra]),
                                 path=path)
    assert len(scored) == 3  # ledger unchanged in size


def test_cli_init_and_score(tmp_path, monkeypatch):
    from etl.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert ledger.main(["--init", "--leagues", LEAGUE]) == 0
    ledger_path = tmp_path / f"predictions_ledger_{LEAGUE}.csv"
    assert ledger_path.exists()

    ledger.append_predictions(LEAGUE, ROWS)  # uses settings.data_dir
    results_csv = tmp_path / "results.csv"
    RESULTS.to_csv(results_csv, index=False)
    assert ledger.main(["--score", "--results", str(results_csv),
                        "--leagues", LEAGUE]) == 0
    df = pd.read_csv(ledger_path)
    assert df.loc[0, "logloss_poisson"] == pytest.approx(-math.log(0.60))
