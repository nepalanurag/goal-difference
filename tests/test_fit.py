"""Tests for etl.fit: probability math and recency weighting."""
from __future__ import annotations

import numpy as np
import pandas as pd

from etl.fit import recency_weights, scoreline_to_1x2


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
