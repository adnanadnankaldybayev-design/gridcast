"""Split-conformal prediction intervals on rolling backtest residuals.

Protocol (leak-free by construction): for evaluation anchor i, the interval
half-width is the (1-alpha) quantile of |residual| over the K most recent
past anchors only. Nothing from the anchor being evaluated or later is read.

Metrics: PICP (hit rate), mean width (MW), and coverage diagnostics by unit,
horizon bucket (0-24h / 24-48h) and day-type slice. Honest expectation:
coverage dips below nominal exactly where residuals shift distribution
(cold snaps, bank holidays).
"""

from __future__ import annotations

import pandas as pd

LEVELS = (80, 90, 95)
CALIB_ANCHORS = 14
HORIZON_BUCKETS = ((0, 24), (24, 48))


def conformal_frame(
    frame: pd.DataFrame,
    levels: tuple[int, ...] = LEVELS,
    calib_anchors: int = CALIB_ANCHORS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (rows, coverage) for one (unit, model) backtest frame.

    rows: per (anchor, timestamp): lower/upper for each level with hit flags.
    coverage: aggregated PICP/width per level (>= calib starts after warmup).
    """
    anchors = list(sorted(frame["anchor"].unique()))
    rows = []
    for i, anchor in enumerate(anchors):
        if i < 1:
            continue
        window = anchors[max(0, i - calib_anchors) : i]
        calib = frame[frame["anchor"].isin(window)]
        resid = (calib["actual"] - calib["predicted"]).abs()
        if len(resid) < 20:
            continue
        block = frame[frame["anchor"] == anchor]
        cols = ["anchor", "timestamp", "horizon_hours", "actual", "predicted", "warmup"]
        out = block[cols].copy()
        for level in levels:
            q = resid.quantile(level / 100)
            out[f"w{level}"] = float(q)
            out[f"hit{level}"] = (block["actual"] - block["predicted"]).abs() <= q
        rows.append(out)
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    conf = pd.concat(rows, ignore_index=True)
    cov = pd.DataFrame(
        [
            {
                "level": lv,
                "picp": float(conf[f"hit{lv}"].mean()),
                "mean_width": float(2 * conf[f"w{lv}"].mean()),
                "coverage_gap": round(float(conf[f"hit{lv}"].mean() - lv / 100), 4),
                "n": len(conf),
            }
            for lv in levels
        ]
    )
    return conf, cov


def slice_coverage(
    confs: pd.DataFrame, unit_date_slices: dict[str, set], unit: str
) -> pd.DataFrame:
    """PICP/width per day-slice x horizon bucket. `unit_date_slices` maps
    slice name -> set of local dates (weekday/weekend/bank_holiday/cold_10pct),
    resolved upstream with the unit's local timezone."""
    from gridcast.eval.slices import _local_dates

    if confs.empty:
        return confs
    local_dates = _local_dates(confs["timestamp"], unit)
    out = []
    for name, dates in unit_date_slices.items():
        mask = local_dates.isin(dates)
        sub = confs[mask]
        for (h0, h1) in HORIZON_BUCKETS:
            mask_h = sub["horizon_hours"].between(h0, h1, inclusive="left")
            s = sub[mask_h]
            if len(s) < 30:
                out.append({"slice": name, "horizon": f"{h0}-{h1}", "n": len(s)})
                continue
            row = {"slice": name, "horizon": f"{h0}-{h1}", "n": len(s)}
            for lv_col in [c for c in confs.columns if c.startswith("hit")]:
                lv = lv_col.replace("hit", "")
                row[f"picp{lv}"] = float(s[lv_col].mean())
                row[f"width{lv}"] = float(2 * s[f"w{lv}"].mean())
            out.append(row)
    return pd.DataFrame(out)
