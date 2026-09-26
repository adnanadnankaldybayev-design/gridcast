"""Forecast error metrics.

- MAE: mean absolute error, MW — primary unit-comparable metric, safe for
  zero/negative demand (SA1 midday).
- sMAPE: 100 * 2|err| / (|y| + |y_hat|), symmetric, bounded in [0, 200],
  robust where demand crosses zero — PRIMARY ratio metric for AU.
- MAPE: 100 * |err| / |y|, computed only where |y| >= mape_floor_mw (huge
  distortion near zero otherwise); we report the exclusion share. GB/IE floors
  are far from zero, so MAPE stays meaningful there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_MAPE_FLOOR_MW = 100.0


def mae(actual: pd.Series, predicted: pd.Series) -> float:
    return float((actual - predicted).abs().mean())


def smape(actual: pd.Series, predicted: pd.Series) -> float:
    denom = actual.abs() + predicted.abs()
    terms = 2.0 * (actual - predicted).abs() / denom.where(denom > 0)
    return float(100.0 * terms.dropna().mean())


def mape(
    actual: pd.Series, predicted: pd.Series, floor_mw: float = DEFAULT_MAPE_FLOOR_MW
) -> tuple[float, float]:
    """Returns (mape_pct, excluded_share). Points with |actual| < floor are
    excluded; the share tells the reader how much was filtered."""
    mask = actual.abs() >= floor_mw
    if mask.sum() == 0:
        return float("nan"), 1.0
    return float(100.0 * ((actual - predicted).abs() / actual.abs())[mask].mean()), float(
        1.0 - mask.mean()
    )


def summarize(
    actual: pd.Series, predicted: pd.Series, floor_mw: float = DEFAULT_MAPE_FLOOR_MW
) -> dict:
    if len(actual) == 0:
        raise ValueError("metrics.summarize: empty input")
    mape_pct, excluded = mape(actual, predicted, floor_mw)
    return {
        "n": len(actual),
        "mae_mw": round(mae(actual, predicted), 3),
        "smape_pct": round(smape(actual, predicted), 4),
        "mape_pct": round(mape_pct, 4),
        "mape_excluded_pct": round(100.0 * excluded, 4),
        "bias_mw": round(float((predicted - actual).mean()), 3),
        "rmse_mw": round(float(np.sqrt(((actual - predicted) ** 2).mean())), 3),
    }
