"""Ridge + Chronos interface tests.

Torch and model weights are never touched: Chronos gets a stub pipeline
injected via _PipelineHolder.set(). Ridge runs on the same offline seeded
synthetic used for the GBM test.
"""

import numpy as np
import pandas as pd
import pytest

from gridcast.features.weather import POINTS, seed_point_data
from gridcast.models.chronos import MAX_CONTEXT, ChronosModel, _PipelineHolder
from gridcast.models.ridge import RidgeModel
from test_gbm import synth_demand, synth_weather

POINTS_GB = POINTS["GB"]


class StubBolt:
    """Stand-in for the bolt pipeline: deterministic [1, 9, steps] output."""

    def __init__(self):
        self.last_steps = None

    def predict(self, context, prediction_length: int):
        self.last_steps = prediction_length
        return np.full((1, 9, prediction_length), 12345.0, dtype="float32")


@pytest.fixture(autouse=True)
def stub_chronos():
    stub = StubBolt()
    _PipelineHolder.set(stub)
    yield stub
    _PipelineHolder.set(None)


def _history(n=3000, start="2026-01-01", step_min=30):
    idx = pd.date_range(start, periods=n, freq=f"{step_min}min", tz="UTC")
    return pd.Series(np.linspace(1000, 2000, n), index=idx)


def test_chronos_fit_is_context_cut_only_and_predict_median(stub_chronos):
    model = ChronosModel("GB", "GB")
    hist = _history(n=MAX_CONTEXT + 500)
    model.fit(hist)
    assert model._context.shape[0] == MAX_CONTEXT  # left-truncated
    ts = pd.date_range(hist.index[-1] + pd.Timedelta(minutes=30), periods=96, freq="30min")
    pred = model.predict(ts)
    assert len(pred) == 96
    assert (pred == 12345.0).all()  # median of constant samples
    assert stub_chronos.last_steps == 96


def test_chronos_fit_rejects_tiny_history():
    with pytest.raises(ValueError, match="too little history"):
        ChronosModel("GB", "GB").fit(_history(n=10))


def test_chronos_predict_before_fit_raises():
    ts = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    with pytest.raises(RuntimeError, match="predict before fit"):
        ChronosModel("GB", "GB").predict(ts)


STEP_MIN = 30
STEPS_PER_DAY = 48


@pytest.fixture
def seeded_weather():
    w = synth_weather()
    for lat, lon, _weight in POINTS_GB:
        seed_point_data(lat, lon, w)
    return w


def test_ridge_beats_naive_on_temperature_driven_demand(seeded_weather):
    from gridcast.models.naive import SeasonalNaive

    demand = synth_demand(seeded_weather)
    cut = demand.index[30 * STEPS_PER_DAY]
    history = demand.loc[:cut]
    horizon = pd.date_range(
        cut + pd.Timedelta(minutes=STEP_MIN), periods=2 * STEPS_PER_DAY, freq="30min"
    )
    actual = demand.loc[horizon]

    ridge = RidgeModel("GB", "GB", use_weather=True)
    ridge.fit(history)
    ridge_mae = (ridge.predict(horizon) - actual).abs().mean()

    naive = SeasonalNaive()
    naive.fit(history)
    naive_mae = (naive.predict(horizon) - actual).abs().mean()

    assert ridge_mae < naive_mae
    assert ridge_mae < 3500


def test_ridge_predict_before_fit_raises():
    ts = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    with pytest.raises(RuntimeError, match="predict before fit"):
        RidgeModel("GB", "GB", use_weather=False).predict(ts)


def test_ridge_linear_solution_matches_closed_form_on_simple_design():
    """On a strictly linear feature->target map with enough rows, ridge must
    approximate the closed-form line (sanity of feature wiring, scaled inputs)."""
    idx = pd.date_range("2026-03-01", periods=2000, freq="30min", tz="UTC")
    hist = pd.Series(1000 + 2.0 * np.arange(2000), index=idx)
    model = RidgeModel("GB", "GB", use_weather=False)
    model.fit(hist)
    horizon = idx[-1] + pd.to_timedelta(np.arange(1, 49), unit="h")
    pred = model.predict(horizon)
    # lags give ridge the trend: should track the line closely, not sit flat
    assert pred.iloc[-1] > pred.iloc[0]
    assert (pred - pd.Series(1000 + 2.0 * np.arange(2000, 2048), index=horizon)).abs().mean() < 400


def test_anchors_stride_subsamples():
    from gridcast.eval.backtest import BacktestConfig, anchors_for

    s = synth_demand(synth_weather()).iloc[: 30 * 48]
    cfg = BacktestConfig(anchors_stride=7)
    a1 = anchors_for(s, s.index[0], s.index[-1], BacktestConfig())
    a7 = anchors_for(s, s.index[0], s.index[-1], cfg)
    assert len(a7) * 7 >= len(a1) >= len(a7)
    assert set(a7) <= set(a1)
    assert a7[0] == a1[0]
