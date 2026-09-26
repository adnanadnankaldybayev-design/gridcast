"""Model comparison runner (H1 harness): same anchors, same config, several
models; writes a combined JSON report + a Markdown verdict file to reports/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridcast.eval.backtest import PRIMARY_METRIC, BacktestConfig, run_backtest
from gridcast.eval.slices import slice_metrics

DEFAULT_MODELS = (
    "seasonal-naive-168h",
    "ridge-weather",
    "lightgbm-weather",
    "chronos-bolt-zero-shot",
)

# Heavyweight models get anchor subsampling; everything else runs full daily.
# stride 6 (not 7): with a 7-day stride every Chronos anchor lands on the SAME
# weekday, which blinds weekday/weekend slices; 6 rotates through the week.
MODEL_ANCHOR_STRIDE = {"chronos-bolt-zero-shot": 6}


def run_comparison(
    markets: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    models=DEFAULT_MODELS,
    refit_every_anchors: int = 7,
    chronos_stride: int = 7,
    units_filter: dict[str, tuple[str, ...]] | None = None,
    data_dir: Path | None = None,
) -> dict:
    """Returns {unit_key: {"models": {model: aggregate}, "slices": ...}}.

    Cross-model numbers are always computed on the COMMON anchor set (the
    intersection of each model's evaluated anchors), so a stride-N Chronos is
    compared to naive/ridge/GBM on exactly the same evaluation points.
    """
    per_model: dict[str, tuple[dict, dict]] = {}
    strides: dict[str, int] = {}
    for model in models:
        stride = chronos_stride if model == "chronos-bolt-zero-shot" else 1
        stride = MODEL_ANCHOR_STRIDE.get(model, stride)
        strides[model] = stride
        cfg = BacktestConfig(
            model=model,
            refit_every_anchors=refit_every_anchors,
            min_history_days=30,  # GBM: 336h lag warmup + 14d early-stop tail + depth
            anchors_stride=stride,
        )
        report, frames = run_backtest(markets, start, end, cfg, data_dir)
        per_model[model] = (report, frames)

    unit_models: dict[str, dict] = {}
    for model, (_report, frames) in per_model.items():
        for key, frame in frames.items():
            market = key.split("/")[0]
            if units_filter and market in units_filter and key not in units_filter[market]:
                continue
            unit_models.setdefault(key, {})[model] = frame

    # aggregates: full engine-side entry per model/unit (overall + by_horizon
    # + by_month + n_anchors), so reports carry the same tables as backtest CLI
    from gridcast.eval.backtest import aggregate

    out: dict = {}
    for key, frame_by_model in unit_models.items():
        market, unit = key.split("/", 1)
        # common evaluation set across models of this unit
        common_anchors = None
        for frame in frame_by_model.values():
            anchors = set(frame["anchor"].unique())
            common_anchors = anchors if common_anchors is None else common_anchors & anchors

        aggregates = {}
        for model, frame in frame_by_model.items():
            primary = PRIMARY_METRIC[market]
            res = per_model[model][0]["results"][market][unit]
            agg = aggregate(frame, BacktestConfig())
            agg["primary_metric"] = primary
            agg["pub_lag_days"] = res["pub_lag_days"]
            agg["n_anchors"] = res["n_anchors"]
            agg["anchors_stride"] = strides[model]
            common = frame[frame["anchor"].isin(common_anchors)]
            common_agg = aggregate(common, BacktestConfig())
            agg["on_common_anchors"] = {
                **common_agg["overall"],
                "n_anchors": int(common["anchor"].nunique()),
            }
            aggregates[model] = agg
        slices = slice_metrics(frame_by_model, unit)
        out[key] = {"models": aggregates, "slices": slices}
    return out


def verdict_table(comparison: dict) -> pd.DataFrame:
    rows = []
    for key, data in comparison.items():
        for model, agg in data["models"].items():
            primary = agg["primary_metric"]
            common = agg["on_common_anchors"]
            rows.append(
                {
                    "unit": key,
                    "model": model,
                    "primary": primary,
                    "primary_value": common[primary],
                    "mae_mw": common["mae_mw"],
                    "n": common["n"],
                    "anchors": common["n_anchors"],
                    "stride": agg["anchors_stride"],
                }
            )
    return pd.DataFrame(rows)


def model_verdicts(comparison: dict, baseline="seasonal-naive-168h") -> dict:
    """Per unit and per model: primary metric on the COMMON anchor set vs the
    seasonal-naive baseline. This is the honest cross-model table."""
    out = {}
    for key, data in comparison.items():
        models_p = data["models"]
        metric = models_p[baseline]["primary_metric"]
        n = models_p[baseline]["on_common_anchors"][metric]
        entries = {}
        for model, agg in models_p.items():
            if model == baseline:
                continue
            m = agg["on_common_anchors"][metric]
            entries[model] = {
                "value": m,
                "delta_pct_points": round(n - m, 3),
                "beats_naive": bool(m < n),
            }
        out[key] = {"metric": metric, "naive": n, "models": entries}
    return out


def render_markdown(comparison: dict, period: tuple[str, str], details: dict) -> str:
    vt = verdict_table(comparison)
    verdicts = model_verdicts(comparison)
    models = list(vt["model"].unique())
    lines = [
        f"# Model zoo comparison — naive vs ridge vs LightGBM vs Chronos "
        f"(period {period[0]}..{period[1]})",
        "",
        "- protocol: rolling-origin, daily anchors 12:00 UTC, 48h horizon, pub-lag cutoffs; "
        f"GBM refit every {details.get('refit_every_anchors', 7)} anchors "
        "(production-style weekly retraining); "
        "anchors need >=30 days of published history (GB: starts ~Apr 21 due to 21d arrears)",
        "- cross-model numbers below are computed on the COMMON anchor set "
        "(intersection of evaluated anchors), so the stride-N Chronos is judged "
        "on exactly the same points as full-daily models",
        "- Chronos-Bolt-mini runs ZERO-SHOT (no fitting, pretrained weights); "
        "CPU-bound, evaluated on every "
        f"{details.get('chronos_stride', 7)}th anchor",
        "- primary metric: MAPE for GB/IE (|y|>=100MW filter), sMAPE for AU (SA1 crosses zero)",
        "",
        "| unit | model | primary | value | MAE (MW) | anchors |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in vt.sort_values(["unit", "model"]).iterrows():
        lines.append(
            f"| {r.unit} | {r.model} | {r.primary} | {r.primary_value} | {r.mae_mw} | {r.anchors} |"
        )

    lines += ["", "## By month (primary metric)", ""]
    for key, data in comparison.items():
        primary = next(iter(data["models"].values()))["primary_metric"]
        lines.append(f"### {key} ({primary})")
        months = sorted(
            {m["month"] for agg in data["models"].values() for m in agg["by_month"]}
        )
        header = "| month |" + "|".join(data["models"]) + "|"
        lines += [header, "|---|" + "---|" * len(data["models"])]
        for m in months:
            cells = []
            for agg in data["models"].values():
                hit = [row for row in agg["by_month"] if row["month"] == m]
                cells.append(str(hit[0][primary]) if hit else "-")
            lines.append(f"| {m} |" + "|".join(cells) + "|")
        lines.append("")

    selected_h = [1.0, 6.0, 12.0, 24.0, 36.0, 48.0]
    lines += ["## By horizon, selected hours (primary metric)", ""]
    for key, data in comparison.items():
        primary = next(iter(data["models"].values()))["primary_metric"]
        lines.append(f"### {key} ({primary})")
        lines += [
            "| horizon h |" + "|".join(data["models"]) + "|",
            "|---|" + "---|" * len(data["models"]),
        ]
        for h in selected_h:
            cells = []
            for agg in data["models"].values():
                hit = [row for row in agg["by_horizon"] if float(row["horizon_hours"]) == h]
                cells.append(str(hit[0][primary]) if hit else "-")
            lines.append(f"| {h} |" + "|".join(cells) + "|")
        lines.append("")

    lines += ["## Verdicts vs seasonal-naive (primary metric, common anchors)", ""]
    for key, v in verdicts.items():
        model_lines = []
        for model in models:
            if model == "seasonal-naive-168h":
                continue
            entry = v["models"].get(model)
            if entry is None:
                continue
            mark = "BEATS" if entry["beats_naive"] else "loses to"
            model_lines.append(
                f"{model} {mark} ({entry['value']}, delta {entry['delta_pct_points']})"
            )
        lines.append(f"- **{key}** (naive {v['metric']}={v['naive']}): " + "; ".join(model_lines))

    lines += ["", "## Day-type slices (primary metric per model)", ""]
    losses = []
    for key, data in comparison.items():
        lines.append(f"### {key}")
        rows = []
        for slice_name, slice_data in data["slices"].items():
            row = {"slice": slice_name, "n_days": slice_data.get("n_days")}
            for model, agg in data["models"].items():
                cell = slice_data.get(model)
                row[model] = None if cell is None else cell[agg["primary_metric"]]
            rows.append(row)
        if rows:
            sdf = pd.DataFrame(rows)
            lines.append(sdf.to_string(index=False))
            naive_col, gbm_col = "seasonal-naive-168h", "lightgbm-weather"
            for _, r in sdf.iterrows():
                present = r.get(gbm_col) is not None and r.get(naive_col) is not None
                if present and r[gbm_col] > r[naive_col]:
                    losses.append(f"{key}/{r['slice']}")
        lines.append("")
    lines += [
        "### Where the weather-GBM LOSES to naive (honest account)",
        "",
        ", ".join(losses) if losses else "nowhere in the measured slices",
        "",
    ]
    return "\n".join(lines) + "\n"
