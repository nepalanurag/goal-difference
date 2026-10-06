"""Tests for etl.fit: probability math, recency weighting, Dixon-Coles."""
from __future__ import annotations

import numpy as np
import pandas as pd

from etl.features import elo_update, load_devigged_odds
from etl.fit import (
    blend_ensemble,
    brier_score_3,
    build_calibration_table,
    dc_scoreline_grid,
    DixonColesModel,
    grid_to_1x2,
    ranked_probability_score,
    recency_weights,
    reshape_grid_to_marginals,
    scoreline_to_1x2,
)


def test_scoreline_sums_to_one():
    for lh, la in [(1.5, 1.2), (0.3, 2.5), (3.0, 0.2), (1e-9, 1e-9)]:
        pa, pd_, ph = scoreline_to_1x2(lh, la)
        assert abs(pa + pd_ + ph - 1.0) < 1e-9
        assert pa >= 0 and pd_ >= 0 and ph >= 0


def test_scoreline_favorites_favorite():
    pa, pd_, ph = scoreline_to_1x2(2.5, 0.5)
    assert ph > pa and ph > pd_


def test_recency_weights_decay():
    dates = pd.Series(pd.to_datetime(["2023-01-01", "2024-01-01", "2024-06-28"]))
    w = recency_weights(dates)
    assert w[2] == 1.0  # most recent gets full weight
    assert w[0] < w[1] < w[2]
    # Half-life check: ~180 days ago -> weight ~0.5.
    dates2 = pd.Series(pd.to_datetime(["2024-01-01", "2024-06-29"]))
    w2 = recency_weights(dates2)
    assert abs(w2[0] - 0.5) < 0.01


def _synthetic_league(seed: int = 7) -> pd.DataFrame:
    """Small synthetic league with known strengths for DC fitting."""
    rng = np.random.default_rng(seed)
    teams = ["A", "B", "C", "D"]
    att = {"A": 0.4, "B": 0.1, "C": -0.1, "D": -0.4}
    dfn = {"A": -0.3, "B": 0.0, "C": 0.1, "D": 0.2}
    rows = []
    base = pd.Timestamp("2024-01-01")
    k = 0
    for _ in range(30):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                lh = np.exp(0.25 + att[h] - dfn[a])
                la = np.exp(att[a] - dfn[h])
                rows.append({
                    "home": h, "away": a,
                    "home_goals": int(rng.poisson(lh)),
                    "away_goals": int(rng.poisson(la)),
                    "date": base + pd.Timedelta(days=k),
                })
                k += 1
    return pd.DataFrame(rows)


def test_dc_fit_converges_and_identifiable():
    df = _synthetic_league()
    m = DixonColesModel()
    assert m.fit(df) is True
    p = m.params
    assert set(p["teams"]) == {"A", "B", "C", "D"}
    assert abs(sum(p["attack"].values())) < 1e-6
    assert abs(sum(p["defense"].values())) < 1e-6
    assert 1e-4 <= p["xi"] <= 1e-2
    assert -0.15 <= p["rho"] <= 0.15
    # Strongest attack team recovered at the top.
    assert p["attack"]["A"] > p["attack"]["D"]
    probs = m.predict_proba(df.head(3))
    assert probs.shape == (3, 3)
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_dc_tau_raises_draw_vs_independent():
    # rho < 0 is the usual football finding: more draws than independent.
    grid = dc_scoreline_grid(1.35, 1.15, rho=-0.13)
    pa, pd_, ph = grid_to_1x2(grid)
    pa0, pd0, ph0 = scoreline_to_1x2(1.35, 1.15)
    assert pd_ > pd0
    assert abs(pa + pd_ + ph - 1.0) < 1e-9


def test_reshape_grid_matches_target_marginals():
    grid = dc_scoreline_grid(1.5, 1.0, rho=-0.05)
    target = np.array([0.2, 0.3, 0.5])
    out = reshape_grid_to_marginals(grid, target)
    assert abs(out.sum() - 1.0) < 1e-9
    assert np.allclose(grid_to_1x2(out), target, atol=1e-9)


def test_blend_is_gbm_dominant():
    p_dc = np.array([[0.3, 0.3, 0.4]])
    p_ml = np.array([[0.2, 0.2, 0.6]])
    assert np.allclose(blend_ensemble(p_dc, p_ml),
                       0.6 * p_ml + 0.4 * p_dc)


def test_brier_and_rps_sanity():
    y = np.array([2, 0, 1])
    perfect = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
    assert brier_score_3(y, perfect) == 0.0
    assert ranked_probability_score(y, perfect) == 0.0
    uniform = np.full((3, 3), 1 / 3)
    assert abs(brier_score_3(y, uniform) - 2 / 3) < 1e-9
    # RPS punishes a predicted home win less when the truth was a draw.
    p_draw_truth = np.array([[0.1, 0.1, 0.8]])
    assert (ranked_probability_score(np.array([1]), p_draw_truth)
            < ranked_probability_score(np.array([0]), p_draw_truth))


def test_elo_home_win_moves_ratings():
    rh, ra = elo_update(1500.0, 1500.0, 2, 0)
    assert rh > 1500.0 > ra
    rh2, ra2 = elo_update(1500.0, 1500.0, 1, 1)
    assert abs(rh2 - 1500.0) < abs(rh - 1500.0)  # draw moves less than a win
    # Bigger margin moves more.
    rh3, _ = elo_update(1500.0, 1500.0, 4, 0)
    assert rh3 > rh


def test_devigged_odds_sum_to_one():
    odds = load_devigged_odds("pl")
    assert len(odds) == 380  # full 2025/26 season covered
    for probs in list(odds.values())[:20]:
        assert abs(sum(probs) - 1.0) < 1e-9
        assert all(0 < p < 1 for p in probs)


def test_calibration_buckets_cover_all_samples():
    y = [2, 0, 1, 2, 2, 0]
    p = [[0.1, 0.2, 0.7], [0.6, 0.2, 0.2], [0.2, 0.5, 0.3],
         [0.1, 0.1, 0.8], [0.2, 0.2, 0.6], [0.5, 0.3, 0.2]]
    buckets = build_calibration_table(y, p, n_bins=5)
    assert len(buckets) == 5
    assert sum(b["n"] for b in buckets) == 3 * len(y)
    for b in buckets:
        if b["n"]:
            assert 0 <= b["observed_rate"] <= 1
            assert b["lo"] <= b["mean_pred"] <= b["hi"] + 1e-9
