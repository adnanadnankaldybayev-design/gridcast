"""Diebold-Mariano predictive-accuracy test with Newey-West HAC variance.

For two aligned forecast frames we compare the loss series d_t = |e1_t| -
|e2_t| over the common evaluation points. The DM statistic uses a HAC
long-run variance (Newey-West with lag floor(T^(1/3), capped), which is
conservative under the serial correlation of rolling-origin forecast
residuals (overlapping 48h horizons overlap massively: honest, and when the
test still says 'significant', the case is strong).

p-values are two-sided normal approximations. Report where differences are
NOT significant — that is a finding, not a failure.
"""

from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd


def _norm_sf(z: float) -> float:
    """Two-sided p-value for |Z| >= z under the standard normal."""
    return 2.0 * (1.0 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def _hac_var(x: np.ndarray, lag: int) -> float:
    """Newey-West long-run variance of the sample mean."""
    n = len(x)
    xc = x - x.mean()
    gamma0 = float(xc @ xc / n)
    var = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        w = 1.0 - k / (lag + 1.0)
        g = float(xc[k:] @ xc[:-k] / n)
        var += 2.0 * w * g
    return var / n  # Var(mean)


def dm_test(
    frame1: pd.DataFrame,
    frame2: pd.DataFrame,
    loss: str = "absolute",
    lag: int | None = None,
) -> dict:
    """Compare forecast accuracy frame1 vs frame2 on common (anchor, timestamp)."""
    m = frame1.merge(
        frame2, on=["anchor", "timestamp"], suffixes=("_1", "_2"), how="inner"
    )
    if len(m) < 30:
        raise ValueError(f"dm_test: only {len(m)} common points")
    e1 = (m["actual_1"] - m["predicted_1"]).abs()
    e2 = (m["actual_2"] - m["predicted_2"]).abs()
    if loss == "squared":
        d = e1.to_numpy() ** 2 - e2.to_numpy() ** 2
    else:
        d = e1.to_numpy() - e2.to_numpy()
    n = len(d)
    if lag is None:
        lag = max(1, int(n ** (1 / 3)))
    stat = float(d.mean())
    var = _hac_var(d, lag)
    z = stat / np.sqrt(var) if var > 0 else 0.0
    return {
        "n": int(n),
        "lag": int(lag),
        "loss": loss,
        "mean_loss_diff": round(float(stat), 6),  # >0 => frame2 is better
        "dm_stat": round(float(z), 4),
        "p_value_two_sided": round(float(_norm_sf(z)), 6),
        "hac_var_mean": float(var),
    }


def aggregate_absolute_errors(frame: pd.DataFrame) -> pd.Series:
    """mean |actual-predicted| per anchor — one observation per issue day."""
    err = (frame["actual"] - frame["predicted"]).abs()
    return err.groupby(frame["anchor"]).mean()


def dm_test_per_anchor(
    frame1: pd.DataFrame,
    frame2: pd.DataFrame,
    lag: int | None = None,
) -> dict:
    """Robust DM: aggregate mean|e| per anchor first, then run the test on the
    aggregated series (n = number of anchors, typically 22-30 per unit).

    Motivation (PROJECT_REBUILD_PLAN P1.1): per-point loss series overlap
    massively across 48h horizons; significance inflated by overlapping
    samples. Per-anchor aggregation is conservative and does not change the
    winner of a comparison, only the confidence of the claim.
    """
    a1 = aggregate_absolute_errors(frame1)
    a2 = aggregate_absolute_errors(frame2)
    joined = pd.concat([a1, a2], axis=1, join="inner").dropna()
    joined.columns = ["l1", "l2"]
    if len(joined) < 8:
        raise ValueError(f"dm_test_per_anchor: only {len(joined)} common anchors")
    d = joined["l1"].to_numpy() - joined["l2"].to_numpy()
    n = len(d)
    if lag is None:
        lag = max(1, int(n ** (1 / 3)))
    stat = float(d.mean())
    var = _hac_var(d, lag)
    z = stat / np.sqrt(var) if var > 0 else 0.0
    return {
        "n_anchors": int(n),
        "lag": int(lag),
        "loss": "absolute-per-anchor",
        "mean_loss_diff": round(float(stat), 6),  # >0 => frame2 (b) is better
        "dm_stat": round(float(z), 4),
        "p_value_two_sided": round(float(_norm_sf(z)), 6),
        "hac_var_mean": float(var),
    }
