"""Metric definitions: exact values on hand-checked examples."""

import numpy as np
import pandas as pd
import pytest

from gridcast.eval.metrics import mae, mape, smape, summarize


def test_exact_values_simple():
    y = pd.Series([100.0, 200.0, 400.0])
    p = pd.Series([110.0, 190.0, 300.0])
    assert mae(y, p) == pytest.approx((10 + 10 + 100) / 3)
    m, excl = mape(y, p)
    assert m == pytest.approx((10 + 5 + 25) / 3)
    assert excl == 0.0
    assert smape(y, p) == pytest.approx(
        100 * (2 * 10 / 210 + 2 * 10 / 390 + 2 * 100 / 700) / 3
    )


def test_smape_handles_zero_crossing_and_bounds():
    y = pd.Series([-50.0, 0.0, 100.0])
    p = pd.Series([50.0, 10.0, 90.0])
    val = smape(y, p)
    assert 0 <= val <= 200
    # y=0, p=10 contributes 200: denom=10 -> 2*10/10=2.0
    pts = 2 * (y - p).abs() / (y.abs() + p.abs())
    assert pts[1] == pytest.approx(2.0)


def test_mape_floor_excludes_near_zero_and_reports_share():
    y = pd.Series([0.5, -2.0, 5000.0, 10000.0])
    p = pd.Series([100.0, 0.0, 5050.0, 9000.0])
    m, excl = mape(y, p, floor_mw=100.0)
    # only the two large values count
    assert m == pytest.approx((1 + 10) / 2)
    assert excl == pytest.approx(0.5)


def test_mape_all_below_floor_is_nan_full_exclusion():
    m, excl = mape(pd.Series([1.0, -1.0]), pd.Series([2.0, 0.0]), floor_mw=100.0)
    assert np.isnan(m)
    assert excl == 1.0


def test_summarize_keys_and_bias_sign():
    out = summarize(pd.Series([100.0, 200.0]), pd.Series([90.0, 220.0]))
    assert out["n"] == 2
    assert out["bias_mw"] == pytest.approx(5.0)  # over-forecast on average
    assert set(out) == {
        "n",
        "mae_mw",
        "smape_pct",
        "mape_pct",
        "mape_excluded_pct",
        "bias_mw",
        "rmse_mw",
    }


def test_summarize_empty_raises():
    with pytest.raises(ValueError):
        summarize(pd.Series(dtype=float), pd.Series(dtype=float))
