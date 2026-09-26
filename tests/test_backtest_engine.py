"""Backtest engine: leakage proofs, DST, gaps, narrow windows, AU aggregation."""

import math
from typing import ClassVar

import numpy as np
import pandas as pd
import pytest

from gridcast.eval.backtest import (
    BacktestConfig,
    anchors_for,
    load_series,
    rolling_origin,
    run_backtest,
)

SIN = math.sin
TAU = 2 * math.pi


def make_cfg(**kw):
    base = dict(step_hours=24, horizon_hours=48, issue_hour_utc=12, train_days=None)
    base.update(kw)
    return BacktestConfig(**base)


def synth_series(days=60, step_min=30, start="2026-02-15"):
    """Deterministic weekly+daily seasonal signal (MW), UTC grid, no gaps."""
    idx = pd.date_range(
        start, periods=days * 1440 // step_min, freq=f"{step_min}min", tz="UTC"
    )
    secs = (idx - idx[0]).total_seconds().to_numpy()
    week, day = 7 * 86400.0, 86400.0
    vals = 5000 + 1500 * np.sin(TAU * ((secs % week) / week)) + 300 * np.sin(
        TAU * ((secs % day) / day)
    )
    return pd.Series(vals, index=idx, name="demand_mw")


class SpyModel:
    """Records its fit window; a correct engine must never feed it the
    unpublished or future part of the series."""
    instances: ClassVar[list["SpyModel"]] = []

    def __init__(self):
        self.cutoff = None
        self.history_len = 0

    def fit(self, history):
        self.cutoff = history.index[-1]
        self.history_len = len(history)
        SpyModel.instances.append(self)

    def predict(self, timestamps):
        return pd.Series(9999.0, index=timestamps)


@pytest.fixture(autouse=True)
def _reset_spy():
    SpyModel.instances = []


def spy_factory(market, unit):
    return SpyModel()


def test_anchors_respect_issue_hour_and_step():
    s = synth_series()
    anchors = anchors_for(
        s,
        pd.Timestamp("2026-03-01", tz="UTC"),
        pd.Timestamp("2026-03-10", tz="UTC"),
        make_cfg(),
    )
    assert len(anchors) == 9
    assert (anchors.hour == 12).all()
    assert anchors[0] == pd.Timestamp("2026-03-01 12:00", tz="UTC")


def test_no_leakage_spy_model_sees_only_published_past():
    s = synth_series()
    cfg = make_cfg(pub_lag_days={"GB": 7.0})
    cfg.make_model = spy_factory  # instance attribute shadows the method
    bt = rolling_origin(
        s,
        "GB",
        "GB",
        cfg,
        pd.Timestamp("2026-03-01", tz="UTC"),
        pd.Timestamp("2026-03-08", tz="UTC"),
    )
    anchors = sorted(bt["anchor"].unique())
    assert len(anchors) == len(SpyModel.instances) > 0
    for model, anchor in zip(SpyModel.instances, anchors, strict=True):
        assert model.history_len > 10
        assert model.cutoff <= anchor - pd.Timedelta(days=7)


def test_future_noise_never_changes_predictions():
    """Poison values after the anchor's publication cutoff must not leak into
    predictions. History is deliberately shorter than one season, so EVERY
    forecast comes from the last-known fallback — the value at the cutoff:
    an engine that reads past the cutoff (e.g. the review's `loc[:anchor]`
    leak) swallows the poison and fails here on all 96 horizon points."""
    idx = pd.date_range("2026-03-08", periods=6 * 48, freq="30min", tz="UTC")
    s_clean = pd.Series(5000 + 500 * np.sin(np.arange(len(idx)) * TAU / 48), index=idx)
    cfg = make_cfg(pub_lag_days={"GB": 0.25})
    start = pd.Timestamp("2026-03-09", tz="UTC")
    end = pd.Timestamp("2026-03-10", tz="UTC")  # anchors_for treats `end` as a midnight bound
    cutoff = pd.Timestamp("2026-03-09 06:00", tz="UTC")  # single anchor 12:00 - 6h lag
    s_noisy = s_clean.copy()
    s_noisy.loc[s_noisy.index > cutoff] = 1e12
    bt_clean = rolling_origin(s_clean, "GB", "GB", cfg, start, end)
    bt_noisy = rolling_origin(s_noisy, "GB", "GB", cfg, start, end)
    merged = bt_clean.merge(
        bt_noisy, on=["anchor", "timestamp"], suffixes=("_clean", "_noisy")
    )
    assert len(merged) == 96
    assert (merged["predicted_clean"] == merged["predicted_noisy"]).all()
    # the poison really sits in the leak window a broken engine would read
    leak_window = s_noisy.loc[cutoff + pd.Timedelta(minutes=30) : cutoff + pd.Timedelta(hours=6)]
    assert (leak_window == 1e12).all()
    # and predictions really exercise the last-known fallback (else the test is blind)
    assert merged["predicted_clean"].nunique() == 1


def test_dst_short_day_keeps_horizon_grid():
    """GB spring forward: dropping the 2 slots of 2026-03-29 00:00-01:00 local
    must not bend the UTC horizon grid (engine keys on timestamps, not counts)."""
    s = synth_series(start="2026-03-20", days=20, step_min=30)
    spring = pd.Timestamp("2026-03-29 01:00", tz="UTC")
    s = s.drop(s.loc[spring : spring + pd.Timedelta(hours=1)].index)
    bt = rolling_origin(
        s,
        "GB",
        "GB",
        make_cfg(pub_lag_days={"GB": 0.25}),
        pd.Timestamp("2026-03-27", tz="UTC"),
        pd.Timestamp("2026-03-29", tz="UTC"),
    )
    assert bt["horizon_hours"].max() == 48.0
    # per anchor, kept points are a sub-grid of the exact 30-min horizon grid;
    # the DST hole appears only as a wider (skipped) gap, never as a bend
    seen_gaps = []
    for _, group in bt.groupby("anchor"):
        diffs = set(group["timestamp"].diff().dropna().unique())
        assert diffs <= {pd.Timedelta(minutes=30), pd.Timedelta(hours=1.5), pd.Timedelta(hours=2)}
        seen_gaps.append(diffs)
    assert any(diffs != {pd.Timedelta(minutes=30)} for diffs in seen_gaps), (
        "no anchor actually crossed the DST hole — test is not exercising the edge"
    )


def test_missing_horizon_points_are_skipped():
    s = synth_series()
    hole = pd.Timestamp("2026-03-12 12:00", tz="UTC")
    hole_idx = pd.date_range(hole, periods=5, freq="30min", tz="UTC")
    s = s.drop(s.loc[hole_idx[0] : hole_idx[-1]].index)
    bt = rolling_origin(
        s,
        "GB",
        "GB",
        make_cfg(pub_lag_days={"GB": 0.25}),
        pd.Timestamp("2026-03-10", tz="UTC"),
        pd.Timestamp("2026-03-11", tz="UTC"),
    )
    assert not bt["timestamp"].isin(hole_idx).any()
    assert len(bt) > 0


def test_backtest_end_to_end_report_structure():
    cfg = make_cfg()
    report, frames = run_backtest(
        ("GB",),
        pd.Timestamp("2026-03-01", tz="UTC"),
        pd.Timestamp("2026-03-31", tz="UTC"),
        cfg,
        series_override={"GB": {"GB": synth_series(start="2026-02-01")}},
    )
    res = report["results"]["GB"]["GB"]
    assert res["n_anchors"] >= 25
    assert res["primary_metric"] == "mape_pct"
    assert set(res["overall"]) >= {"n", "mae_mw", "smape_pct", "mape_pct"}
    assert frames["GB/GB"]["horizon_hours"].max() == 48.0
    horizons = {h["horizon_hours"] for h in res["by_horizon"]}
    assert 48.0 in horizons
    months = {m["month"] for m in res["by_month"]}
    assert "2026-03" in months
    # naive error on a weekly seasonal synthetic must be sane
    assert res["overall"]["mape_pct"] < 30


def test_load_series_builds_nem_total(tmp_path):
    from gridcast.ingest.base import normalize, write_parquet

    ts = pd.date_range("2026-03-01", periods=24, freq="5min", tz="UTC")
    frames = []
    for i, region in enumerate(["NSW1", "QLD1", "SA1", "TAS1", "VIC1"]):
        frames.append(
            normalize(
                pd.DataFrame({"timestamp": ts, "demand_mw": 1000.0 + i, "forecast_mw": pd.NA}),
                "AU",
                region,
                "test",
            )
        )
    write_parquet(pd.concat(frames), "AU", tmp_path)
    units = load_series("AU", tmp_path)
    assert set(units) == {"NSW1", "QLD1", "SA1", "TAS1", "VIC1", "NEM_TOTAL"}
    assert units["NEM_TOTAL"].iloc[0] == 1000.0 * 5 + sum(range(5))


def test_ablation_wiring_no_weather_gets_no_weather():
    """Regression (2026-09-26): make_model used endswith("weather"), which is
    true for BOTH models -> the no-weather ablation silently ran with weather
    and produced identical metrics. The verdicts depend on this wiring."""
    cfg_w = BacktestConfig(model="lightgbm-weather")
    cfg_n = BacktestConfig(model="lightgbm-no-weather")
    assert cfg_w.make_model("GB", "GB").use_weather is True
    assert cfg_n.make_model("GB", "GB").use_weather is False
