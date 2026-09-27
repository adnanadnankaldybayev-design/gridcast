"""E5 ensemble: inverse-MAE weighted combination of model frames, computed
post-hoc from per-model backtest frames — the combination itself is re-derived
per anchor with information strictly from the past.

Weight rule (documented, no fitting on the evaluation window):
  - per anchor a, each member's weight w_m ∝ 1 / (MAE_m over the previous K
    anchors of this unit + eps), K = ROLLING_WEIGHT_ANCHORS (14);
  - with fewer than MIN_WEIGHT_ANCHORS (5) past anchors: equal weights;
  - predictions for an anchor come from member models that only saw data
    published by that anchor (protocol already enforces this — the ensemble
    adds nothing new on the leakage front).

The spy property is tested: permuting any FUTURE anchor's residual vector
never changes a weight (weights only ever read the past K anchors).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ROLLING_WEIGHT_ANCHORS = 14
MIN_WEIGHT_ANCHORS = 5
EPS_MW = 1e-6


def member_mae_by_anchor(frame: pd.DataFrame) -> pd.Series:
    err = frame.assign(err=(frame["actual"] - frame["predicted"]).abs())
    return err.groupby("anchor")["err"].mean().sort_index()


def weight_table(mae_by_anchor: dict[str, pd.Series]) -> pd.DataFrame:
    """w[anchor, model] = inverse-MAE over previous K anchors (past-only)."""
    members = list(mae_by_anchor)
    anchors = sorted(set().union(*(s.index for s in mae_by_anchor.values())))
    rows = []
    for j, anchor in enumerate(anchors):
        past = anchors[max(0, j - ROLLING_WEIGHT_ANCHORS) : j]
        maes = {}
        for m in members:
            s = mae_by_anchor[m].reindex(past).dropna()
            maes[m] = float(s.mean()) if len(s) else None
        valid = {m: v for m, v in maes.items() if v is not None}
        if len(past) < MIN_WEIGHT_ANCHORS or len(valid) < 2:
            w = {m: 1.0 / len(members) for m in members}
        else:
            inv = {m: 1.0 / (v + EPS_MW) for m, v in valid.items()}
            z = sum(inv.values())
            w = {m: inv.get(m, 0.0) / z for m in members}
        rows.append({"anchor": anchor, **{f"w_{m}": w[m] for m in members}})
    return pd.DataFrame(rows)


def ensemble_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine member frames into one weighted frame (same schema)."""
    maes = {m: member_mae_by_anchor(f) for m, f in frames.items()}
    w = weight_table(maes)
    members = list(frames)
    # canonical actual/geometry comes from the first member; every other member
    # is checked to share the same evaluation universe before its preds join
    key = ["anchor", "timestamp", "horizon_hours", "warmup"]
    merged = frames[members[0]][[*key, "actual", "predicted"]].rename(
        columns={"predicted": f"pred_{members[0]}"}
    )
    for m in members[1:]:
        cols = frames[m][[*key, "actual", "predicted"]].rename(
            columns={"actual": f"actual_{m}", "predicted": f"pred_{m}"}
        )
        before = len(merged)
        chk = merged.merge(cols, on=key, how="inner")
        if len(chk) < before * 0.999999 or not np.allclose(
            chk["actual"], chk[f"actual_{m}"], rtol=0, atol=1e-6
        ):
            raise ValueError(
                f"ensemble_frame: member {m!r} misaligned on (anchor,timestamp,actual) "
                f"— refusing to combine frames that do not share one evaluation universe"
            )
        merged = chk.drop(columns=[f"actual_{m}"])
    out = merged.merge(w, on="anchor", how="left")
    pred = sum(out[f"pred_{m}"] * out[f"w_{m}"] for m in members)
    return pd.DataFrame(
        {
            "anchor": out["anchor"],
            "timestamp": out["timestamp"],
            "horizon_hours": out["horizon_hours"],
            "actual": out["actual"],
            "predicted": pred,
            "warmup": out["warmup"],
        }
    )
