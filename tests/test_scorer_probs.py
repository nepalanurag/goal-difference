"""Tests for etl/scorer_probs.py (Phase 8.2 math)."""
from __future__ import annotations

import math

import pytest

from etl.scorer_probs import (
    PENALTY_UPLIFT,
    PRIOR_90S,
    PRIOR_GOALS,
    _expected_minutes,
    normalize_laliga_team,
    scorer_prob,
    shrunk_per90,
)


def test_shrunk_per90_regresses_to_prior():
    # 5 goals in 450 minutes: (5+2)/(5+10) = 7/15
    assert shrunk_per90(5, 450) == (5 + PRIOR_GOALS) / (5 + PRIOR_90S)
    # tiny sample regresses hard toward the prior
    tiny = shrunk_per90(1, 20)
    prior = PRIOR_GOALS / PRIOR_90S
    assert abs(tiny - prior) < abs(1 / (20 / 90) - prior)
    # big sample converges toward the raw rate (prior weight fades)
    big = shrunk_per90(30, 2700)
    assert PRIOR_GOALS / PRIOR_90S < big < 30 / 30
    assert abs(big - 30 / 30) < 0.25


def test_scorer_prob_is_one_minus_exp():
    x_minutes, team_xg, league_avg = 90.0, 1.8, 1.5
    rate = shrunk_per90(5, 450)
    x = rate * (x_minutes / 90.0) * (team_xg / league_avg)
    assert scorer_prob(rate, x_minutes, team_xg, league_avg) == \
        1 - math.exp(-x)


def test_scorer_prob_scales_with_team_xg():
    rate = shrunk_per90(5, 450)
    low = scorer_prob(rate, 90.0, 1.0, 1.5)
    high = scorer_prob(rate, 90.0, 2.5, 1.5)
    assert high > low


def test_penalty_uplift_multiplies_x():
    rate = shrunk_per90(5, 450)
    base = scorer_prob(rate, 90.0, 1.8, 1.5)
    boosted = scorer_prob(rate, 90.0, 1.8, 1.5, penalty=True)
    x = -math.log(1 - base)
    assert boosted == pytest.approx(1 - math.exp(-x * PENALTY_UPLIFT))
    assert boosted > base


def test_expected_minutes_capped_at_90():
    assert _expected_minutes({"minutes": 450, "appearances": 5}) == 90.0
    assert _expected_minutes({"minutes": 450, "appearances": 5,
                              "starts": 5, "_league": "x"}) == 90.0
    # per-appearance rate below 90 is kept
    assert _expected_minutes({"minutes": 200, "appearances": 5}) == 40.0
    # PL non-starter with no starts: bench-role cap
    assert _expected_minutes({"minutes": 120, "appearances": None,
                              "starts": 0, "_league": "pl"}) == 45.0
    # PL starter: minutes per start
    assert _expected_minutes({"minutes": 270, "appearances": None,
                              "starts": 3, "_league": "pl"}) == 90.0


def test_normalize_laliga_team():
    assert normalize_laliga_team("Valencia Club de Fútbol SAD") == "Valencia"
    assert normalize_laliga_team("Club Atlético de Madrid SAD") == "Ath Madrid"
    assert normalize_laliga_team("RCD Espanyol de Barcelona") == "Espanyol"
    assert normalize_laliga_team("Fútbol Club Barcelona") == "Barcelona"
    assert normalize_laliga_team("Real Club Celta de Vigo SAD") == "Celta"
    assert normalize_laliga_team("Real Racing Club SAD") == "Santander"
    # reserve sides and foreign clubs map to None (no team link)
    assert normalize_laliga_team("R. Sociedad B") is None
    assert normalize_laliga_team("RC Celta Fortuna") is None
    assert normalize_laliga_team("Strasbourg") is None
    assert normalize_laliga_team(None) is None
