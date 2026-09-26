"""Regression (E4 review): every cross-model table — above all the day-type
slices — must be computed on the COMMON anchor intersection. A stride-N model
evaluated on ~3 cold days used to be presented side by side with full-daily
models measured on 23 ('chronos best on cold days'), with n_days printed
identically for all columns. These tests pin the fix."""

import pandas as pd
import pytest

from gridcast.eval.compare import common_anchor_frames
from gridcast.eval.slices import slice_metrics
from gridcast.features.weather import POINTS, VARIABLES, seed_point_data


def _frame(anchors, offset):
    """One perfect-grid frame: 4 horizon steps per anchor; actual = anchor hour
    + offset, predicted = actual (zero error)."""
    rows = []
    for a in anchors:
        for h in range(1, 5):
            t = a + pd.Timedelta(hours=h)
            rows.append(
                {
                    "anchor": a,
                    "timestamp": t,
                    "horizon_hours": float(h),
                    "actual": float(a.hour + offset + h),
                    "predicted": float(a.hour + offset + h),
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def gb_weather_seeded():
    """Weather for GB points covering climatology reference + eval window."""
    idx = pd.date_range("2025-01-01", periods=545 * 24, freq="h", tz="UTC")
    w = pd.DataFrame(8.0, index=idx, columns=list(VARIABLES), dtype="float32")
    for lat, lon, _w in POINTS["GB"]:
        seed_point_data(lat, lon, w)
    return w


def test_common_anchor_frames_intersects():
    full = pd.date_range("2026-05-01 12:00", periods=18, freq="D", tz="UTC")
    strided = full[::6]  # every 6th anchor
    frames = {"naive": _frame(full, 0), "chronos": _frame(strided, 1)}
    common = common_anchor_frames(frames)
    assert set(common["naive"]["anchor"].unique()) == set(strided)
    assert set(common["chronos"]["anchor"].unique()) == set(strided)
    assert len(common["naive"]) == len(common["chronos"]) == len(strided) * 4


def test_slices_count_identical_rows_per_model_on_common_frames(gb_weather_seeded):
    full = pd.date_range("2026-05-01 12:00", periods=18, freq="D", tz="UTC")
    strided = full[::6]
    frames = {"naive": _frame(full, 0), "chronos": _frame(strided, 1)}

    # the old (fixed) path: strided models were sliced on their own few anchors
    raw = slice_metrics(frames, "GB")
    assert raw["weekday"]["chronos"]["n"] < raw["weekday"]["naive"]["n"]

    common = common_anchor_frames(frames)
    sliced = slice_metrics(common, "GB")
    for name, data in sliced.items():
        for model in ("naive", "chronos"):
            cell = data.get(model)
            ref = data.get("naive")
            assert (cell is None) == (ref is None), f"{name}/{model}"
            if cell is not None:
                assert cell["n"] == ref["n"], f"{name}: {model} judged on different rows"
