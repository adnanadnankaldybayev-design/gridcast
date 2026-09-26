"""SeasonalNaive unit tests on synthetic series."""

import pandas as pd
import pytest

from gridcast.models.naive import SeasonalNaive


def weekly_series(start="2026-03-01", weeks=4, step="30min", noise=0.0):
    idx = pd.date_range(start, periods=48 * 7 * weeks, freq=step, tz="UTC")
    week = [1000 + 500 * (i % 96) for i in range(48 * 7)]
    values = (week * weeks)[: len(idx)]
    return pd.Series(values, index=idx)


def test_zero_error_on_perfect_weekly_seasonality():
    s = weekly_series()
    cut = s.index[48 * 7 * 2]
    model = SeasonalNaive()
    model.fit(s.loc[:cut])
    horizon = pd.date_range(cut + pd.Timedelta(minutes=30), periods=96, freq="30min")
    pred = model.predict(horizon)
    err = (pred - s.loc[horizon]).abs().max()
    assert err == 0.0


def test_prediction_is_exactly_the_slot_a_week_ago():
    s = weekly_series()  # 30-min steps
    model = SeasonalNaive()
    model.fit(s)
    ts = s.index[-1] + pd.Timedelta(hours=1)
    pred = model.predict(pd.DatetimeIndex([ts]))
    # ts - 168h is 334 steps (30 min each) before the last point
    assert pred.iloc[0] == s.iloc[-1 - 334]


def test_gap_falls_back_to_two_seasons_ago():
    s = weekly_series()
    hole_start = s.index[48 * 7 * 2 + 10]
    s = s.drop(s.loc[hole_start : hole_start + pd.Timedelta(hours=2)].index)
    model = SeasonalNaive()
    model.fit(s)
    target = hole_start + pd.Timedelta(weeks=1)  # target-1w sits inside the hole
    pred = model.predict(pd.DatetimeIndex([target]))
    assert pred.iloc[0] == s.loc[target - pd.Timedelta(weeks=2)]


def test_out_of_lookback_falls_back_to_last_known():
    s = weekly_series()
    model = SeasonalNaive()
    model.fit(s.iloc[:96])  # two days only — a whole season back doesn't exist
    pred = model.predict(pd.DatetimeIndex([s.index[95] + pd.Timedelta(minutes=30)]))
    assert pred.iloc[0] == s.iloc[95]


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="predict before fit"):
        SeasonalNaive().predict(pd.DatetimeIndex([pd.Timestamp("2026-01-01", tz="UTC")]))
