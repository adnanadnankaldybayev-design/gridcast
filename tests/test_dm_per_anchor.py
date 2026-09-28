"""Per-anchor DM: conservative-vs-pointwise behaviour pinned on synthetic frames.

Aggregating mean|e| to one observation per issue day removes the overlap
boost of the per-point form; both behaviours are pinned here.
"""

import pandas as pd
import pytest

from gridcast.eval.dm import aggregate_absolute_errors, dm_test, dm_test_per_anchor
from test_e56 import _frame


def test_aggregate_absolute_errors_shape_and_mean():
    f = _frame(anchors=10, seed=1, err_sigma=100)
    agg = aggregate_absolute_errors(f)
    assert len(agg) == f["anchor"].nunique()
    mean_direct = (f["actual"] - f["predicted"]).abs().mean()
    assert agg.mean() == pytest.approx(mean_direct)


def test_per_anchor_p_high_on_identical_models():
    f = _frame(anchors=60, seed=7, err_sigma=100)
    out = dm_test_per_anchor(f, f.copy())
    assert out["p_value_two_sided"] > 0.2
    assert out["n_anchors"] == 60


def test_per_anchor_p_low_on_strong_difference():
    f1 = _frame(anchors=60, seed=7, err_sigma=200)
    f3 = _frame(anchors=60, seed=8, err_sigma=50)
    out = dm_test_per_anchor(f1, f3)
    assert out["p_value_two_sided"] < 0.05


def test_per_anchor_is_more_conservative_than_pointwise():
    """On the same comparison the per-anchor p is >= the per-point p: horizon
    overlap inflates significance in the per-point form — exactly the
    rigorous claim this robustness test verifies."""
    base = _frame(anchors=60, seed=3, err_sigma=150)
    challenger = _frame(anchors=60, seed=4, err_sigma=120)
    pw = dm_test(base, challenger)["p_value_two_sided"]
    pa = dm_test_per_anchor(base, challenger)["p_value_two_sided"]
    assert pa >= pw
    assert 0.0 <= pa <= 1.0


def test_per_anchor_raises_on_too_few_anchors():
    f1 = _frame(anchors=3, seed=9)
    with pytest.raises(ValueError, match="only"):
        dm_test_per_anchor(f1, f1.copy())
