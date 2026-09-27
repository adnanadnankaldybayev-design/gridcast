"""E5+E6 analysis runner: ensemble combination, Diebold-Mariano tests,
split-conformal intervals, champion selection and the benchmark card —
all derived from one shared, leak-free stride anchor set.

Same-anchor discipline: every member runs with the SAME `anchors_stride`
(6: rotates weekdays), so the ensemble weights, DM tests and coverage numbers
live on one evaluation universe per unit.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from gridcast.eval.backtest import (
    PRIMARY_METRIC,
    BacktestConfig,
    aggregate,
    load_series,
    rolling_origin,
)
from gridcast.eval.conformal import conformal_frame, slice_coverage
from gridcast.eval.dm import dm_test
from gridcast.eval.ensemble_eval import ensemble_frame
from gridcast.eval.slices import _cold_dates_with_provenance, _slice_dates

log = logging.getLogger(__name__)

MEMBERS = (
    "seasonal-naive-168h",
    "ridge-weather",
    "lightgbm-weather",
    "chronos-bolt-zero-shot",
)
ENSEMBLE = "ensemble-inv-mae-14"
DM_PAIRS = (
    ("lightgbm-weather", "seasonal-naive-168h"),
    ("lightgbm-weather", "ridge-weather"),
    ("lightgbm-weather", "chronos-bolt-zero-shot"),
)
CONFORMAL_MODELS = (ENSEMBLE, "lightgbm-weather")


def member_frames(
    market: str,
    unit: str,
    series: pd.Series,
    cfg: BacktestConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    out = {}
    for model in MEMBERS:
        cfg_m = BacktestConfig(
            model=model,
            refit_every_anchors=cfg.refit_every_anchors,
            min_history_days=cfg.min_history_days,
            anchors_stride=cfg.anchors_stride,
        )
        out[model] = rolling_origin(series, unit, market, cfg_m, start, end)
    return out


def analyze_unit(
    market: str, unit: str, frames: dict[str, pd.DataFrame], cfg: BacktestConfig
) -> dict:
    """Full E5/E6 metrics for one unit given per-model frames."""
    primary = PRIMARY_METRIC[market]
    frames[ENSEMBLE] = ensemble_frame({m: f for m, f in frames.items()})
    metrics = {}
    for model, frame in frames.items():
        agg = aggregate(frame, cfg)
        agg["primary_metric"] = primary
        metrics[model] = agg

    best_single = min(
        (m for m in MEMBERS), key=lambda m: metrics[m]["overall"][primary]
    )
    dm_results = {}
    for a, b in DM_PAIRS:
        dm_results[f"{a}__vs__{b}"] = dm_test(frames[a], frames[b])
    dm_results[f"{ENSEMBLE}__vs__{best_single}"] = dm_test(
        frames[ENSEMBLE], frames[best_single]
    )

    slices = _slice_dates(frames[ENSEMBLE], unit)
    cold, cold_meta = _cold_dates_with_provenance(frames[ENSEMBLE], unit)
    slices["cold_10pct"] = cold
    conformal = {}
    for model in CONFORMAL_MODELS:
        conf, cov = conformal_frame(frames[model])
        conformal[model] = {
            "coverage": cov.to_dict(orient="records"),
            "by_slice": slice_coverage(conf, slices, unit).to_dict(orient="records"),
        }

    champion = min(metrics, key=lambda m: metrics[m]["overall"][primary])
    return {
        "unit": unit,
        "primary_metric": primary,
        "n_anchors": {m: int(f["anchor"].nunique()) for m, f in frames.items()},
        "metrics": metrics,
        "best_single_model": best_single,
        "champion_model": champion,
        "dm": dm_results,
        "conformal": conformal,
        "cold_slice": cold_meta,
    }


def run_analysis(
    markets: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    anchors_stride: int = 6,
    refit_every_anchors: int = 7,
    units: dict[str, tuple[str, ...]] | None = None,
    data_dir: Path | None = None,
) -> dict:
    cfg = BacktestConfig(
        refit_every_anchors=refit_every_anchors,
        min_history_days=30,
        anchors_stride=anchors_stride,
    )
    results = {}
    for market in markets:
        series_map = load_series(market, data_dir)
        for unit, series in series_map.items():
            if units and market in units and unit not in units[market]:
                continue
            log.info("analyze %s/%s: members...", market, unit)
            frames = member_frames(market, unit, series, cfg, start, end)
            results[f"{market}/{unit}"] = analyze_unit(market, unit, frames, cfg)
    return {
        "anchors_stride": anchors_stride,
        "refit_every_anchors": refit_every_anchors,
        "min_history_days": cfg.min_history_days,
        "members": list(MEMBERS),
        "results": results,
    }
