"""Tests for etl.pam_select: group mapping, decoy logic, pi threshold."""
from __future__ import annotations

import numpy as np
import pandas as pd

from etl.pam_select import (
    GROUP_ORDER,
    assign_group,
    decoy_copy,
    feature_groups,
    group_beats_decoys,
    jaccard,
    run_pam,
    select_groups,
    selection_frequencies,
)


def _real_feature_cols() -> list[str]:
    df = pd.read_csv("data/features_pl.csv", nrows=0)
    from etl.features import feature_columns
    return feature_columns(df)


def test_assign_group_covers_every_real_feature():
    cols = _real_feature_cols()
    assert len(cols) == 74
    groups = feature_groups(cols)
    assert set(groups) <= set(GROUP_ORDER)
    flat = [c for cs in groups.values() for c in cs]
    assert sorted(flat) == sorted(cols)  # no column dropped or doubled


def test_assign_group_spot_checks():
    assert assign_group("h_w5") == "form"
    assert assign_group("a_momentum") == "form"
    assert assign_group("h_home_ppg") == "venue"
    assert assign_group("a_away_ga_pg") == "venue"
    assert assign_group("h_gf_pg_l5") == "attack_defense"
    assert assign_group("h_cs_rate") == "attack_defense"
    assert assign_group("a_shot_diff_pg") == "shots"
    assert assign_group("h_cards_pg") == "discipline"
    assert assign_group("h2h_edge") == "h2h"
    assert assign_group("a_travel_km") == "rest_travel"
    assert assign_group("h_euro_midweek") == "european"
    assert assign_group("a_key_absences") == "absences"
    assert assign_group("h_elo") == "elo"
    assert assign_group("elo_diff") == "elo"
    assert assign_group("odds_p_home") == "odds"
    assert assign_group("odds_available") == "odds"


def test_decoy_is_row_permutation():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 4))
    D = decoy_copy(X, rng)
    assert D.shape == X.shape
    for j in range(X.shape[1]):
        assert sorted(D[:, j]) == sorted(X[:, j])  # same values
    assert not np.array_equal(D, X)  # overwhelmingly likely reordered


def test_group_beats_decoys_strict():
    gains = {"g_a": 3.0, "g_b": 1.0, "d1": 2.0, "d2": 2.0}
    assert group_beats_decoys(gains, ["g_a", "g_b"], [["d1"], ["d2"]])
    # Tie goes to the decoy (conservative).
    assert not group_beats_decoys({"g": 2.0, "d": 2.0}, ["g"], [["d"]])
    assert not group_beats_decoys({"g": 1.0, "d": 2.0}, ["g"], [["d"]])


def test_select_groups_pi_threshold():
    freqs = {"elo": 0.9, "odds": 0.6, "form": 0.59, "venue": 0.0}
    sel = select_groups(freqs, pi=0.6)
    assert "elo" in sel and "odds" in sel
    assert "form" not in sel and "venue" not in sel


def test_jaccard():
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"a"}, set()) == 0.0
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0


def _synthetic_pam_df(seed: int = 3) -> tuple[pd.DataFrame, list[str]]:
    """One informative group (elo) plus noise; 3-class outcome."""
    rng = np.random.default_rng(seed)
    n = 400
    cols = ["h_elo", "a_elo", "elo_diff",
            "h_w5", "a_w5", "h_shots_pg", "a_shots_pg"]
    X = rng.normal(size=(n, len(cols)))
    edge = (X[:, 0] - X[:, 1]) * 2.0
    logits = np.stack([-edge, np.zeros(n), edge], axis=1)
    probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=p) for p in probs])
    df = pd.DataFrame(X, columns=cols)
    df["result"] = y
    return df, cols


def test_selection_frequencies_finds_signal_group():
    df, cols = _synthetic_pam_df()
    groups = feature_groups(cols)
    assert set(groups) == {"elo", "form", "shots"}
    freqs = selection_frequencies(df, cols, groups, K=2, B=6, seed=11)
    assert freqs["elo"] >= 0.6  # real signal beats noise decoys
    sel = select_groups(freqs, pi=0.6)
    assert "elo" in sel


def test_run_pam_output_shape():
    df, cols = _synthetic_pam_df()
    res = run_pam(df, cols, K=2, B=4, pi=0.6, seed=11, stability=False)
    assert res["jaccard_stability"] is None
    assert set(res["selection_frequency"]) == {"elo", "form", "shots"}
    assert all(0.0 <= f <= 1.0 for f in res["selection_frequency"].values())
    assert set(res["selected_features"]) <= set(cols)
    for g in res["selected_groups"]:
        assert res["selection_frequency"][g] >= 0.6


def test_run_pam_stability_halves():
    df, cols = _synthetic_pam_df()
    res = run_pam(df, cols, K=2, B=4, pi=0.6, seed=11, stability=True)
    assert res["jaccard_stability"] is not None
    assert 0.0 <= res["jaccard_stability"] <= 1.0
    assert set(res["stability_halves"]) == {"first", "second"}
