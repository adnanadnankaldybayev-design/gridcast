"""Model comparison runner (H1 harness): same anchors, same config, several
models; writes a combined JSON report + a Markdown verdict file to reports/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridcast.eval.backtest import PRIMARY_METRIC, BacktestConfig, run_backtest
from gridcast.eval.slices import slice_metrics

DEFAULT_MODELS = ("seasonal-naive-168h", "lightgbm-weather", "lightgbm-no-weather")


def run_comparison(
    markets: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    models=DEFAULT_MODELS,
    refit_every_anchors: int = 7,
    units_filter: dict[str, tuple[str, ...]] | None = None,
    data_dir: Path | None = None,
) -> dict:
    """Returns {unit_key: {"models": {model: aggregate}, "slices": ...}}."""
    per_model: dict[str, tuple[dict, dict]] = {}
    for model in models:
        cfg = BacktestConfig(
            model=model,
            refit_every_anchors=refit_every_anchors,
            min_history_days=30,  # GBM: 336h lag warmup + 14d early-stop tail + depth
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
        aggregates = {}
        for model, frame in frame_by_model.items():
            primary = PRIMARY_METRIC[market]
            res = per_model[model][0]["results"][market][unit]
            agg = aggregate(frame, BacktestConfig())
            agg["primary_metric"] = primary
            agg["pub_lag_days"] = res["pub_lag_days"]
            agg["n_anchors"] = res["n_anchors"]
            aggregates[model] = agg
        slices = slice_metrics(frame_by_model, unit)
        out[key] = {"models": aggregates, "slices": slices}
    return out


def verdict_table(comparison: dict) -> pd.DataFrame:
    rows = []
    for key, data in comparison.items():
        for model, agg in data["models"].items():
            primary = agg["primary_metric"]
            overall = agg["overall"]
            rows.append(
                {
                    "unit": key,
                    "model": model,
                    "primary": primary,
                    "primary_value": overall[primary],
                    "mae_mw": overall["mae_mw"],
                    "n": overall["n"],
                }
            )
    return pd.DataFrame(rows)


def h1_verdicts(comparison: dict, naive="seasonal-naive-168h", gbm="lightgbm-weather") -> dict:
    """Per unit: does GBM(weather) beat naive on the primary metric?"""
    out = {}
    for key, data in comparison.items():
        models_p = data["models"]
        metric = models_p[naive]["primary_metric"]
        n = models_p[naive]["overall"][metric]
        g = models_p[gbm]["overall"][metric]
        out[key] = {
            "metric": models_p[naive]["primary_metric"],
            "naive": n,
            "gbm_weather": g,
            "delta_pct_points": round(n - g, 3),
            "gbm_beats_naive": bool(g < n),
        }
    return out


def render_markdown(comparison: dict, period: tuple[str, str], details: dict) -> str:
    vt = verdict_table(comparison)
    hv = h1_verdicts(comparison)
    lines = [
        f"# H1 comparison — naive vs LightGBM (period {period[0]}..{period[1]})",
        "",
        "- protocol: rolling-origin, daily anchors 12:00 UTC, 48h horizon, pub-lag cutoffs; "
        f"GBM refit every {details.get('refit_every_anchors', 7)} anchors "
        "(production-style weekly retraining); "
        "anchors need >=30 days of published history (GB: starts ~Apr 21 due to 21d arrears)",
        "- weather-ablation note: archive weather = perfect-forecast proxy; "
        "`lightgbm-no-weather` bounds the marginal value a real NWP forecast could add",
        "- primary metric: MAPE for GB/IE (|y|>=100MW filter), sMAPE for AU (SA1 crosses zero)",
        "",
        "| unit | model | primary | value | MAE (MW) |",
        "|---|---|---|---|---|",
    ]
    for _, r in vt.sort_values(["unit", "model"]).iterrows():
        lines.append(f"| {r.unit} | {r.model} | {r.primary} | {r.primary_value} | {r.mae_mw} |")

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

    lines += ["## H1 verdicts (primary metric, lower is better)", ""]
    for key, v in hv.items():
        mark = "BEATS" if v["gbm_beats_naive"] else "LOSES TO"
        lines.append(
            f"- **{key}**: GBM {mark} naive — {v['metric']} {v['gbm_weather']} vs {v['naive']} "
            f"(delta {v['delta_pct_points']} pts)"
        )

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
