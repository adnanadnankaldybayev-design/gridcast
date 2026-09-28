"""Daily forecast pipeline (E9): champions per unit, production-leak-free.

For each unit:
  1. take full published history (demand_mw, non-null), cut at issue - pub_lag,
  2. fit the champion model per unit (single model or the ensemble: members
     naive/ridge/gbm with inverse-MAE weights from rolling residual anchors,
     equal weights while warming up — same rule as E5; no chronos in the
     daily runner so CI stays torch-free, documented),
  3. predict the next HORIZON_H at the market cadence using the NWP forecast
     (Open-Meteo forecast API — NOT the archive),
  4. low/high prediction intervals from rolling residual quantiles,
  5. emit a dated snapshot (data/forecasts/YYYY-MM-DD_{unit}.json, gitignored)
     and the dashboard files site/data/latest_forecasts.json +
     site/data/forecast_history.json (small, committed).

No information newer than (issue - pub_lag) ever enters fit history or
features; the leak-guard test pins this by spying on the model's history.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from gridcast.config import CADENCE_MINUTES, REPO_ROOT
from gridcast.eval.backtest import PUB_LAG_DAYS
from gridcast.eval.ensemble_eval import EPS_MW
from gridcast.features.weather import (
    unit_weather_forecast,
)
from gridcast.ingest.base import IngestError, read_processed
from gridcast.models.gbm import GBMModel
from gridcast.models.naive import SeasonalNaive
from gridcast.models.ridge import RidgeModel

log = logging.getLogger(__name__)

HORIZON_H = 48
RESIDUAL_ANCHORS = 14       # rolling anchors used twice: ensemble weights + intervals
HISTORY_DAYS = 150          # fit window (production retrain at issue)
MIN_HISTORY_POINTS = 200
CHAMPION_DEFAULT = "lightgbm"
ENSEMBLE_MEMBERS = ("naive", "ridge", "lightgbm")
INTERVAL_LEVELS = (80, 90)

UNIT_CHAMPIONS: dict[str, str] = {
    "GB": "ensemble",
    "ALL": "lightgbm",
    "NEM_TOTAL": "ridge",
    "NSW1": "ensemble",
    "QLD1": "lightgbm",
    "SA1": "lightgbm",
    "TAS1": "ensemble",
    "VIC1": "ridge",
    # measured 2026-09-27 analyze run (FR/DE/BE/DK/KZ markets)
    "FR": "ensemble",
    "DE": "ensemble",
    "BE": "lightgbm",
    "DK": "naive",
    "KZ": "naive",
    "KZ_W": "naive",
}

MARKET_UNITS: dict[str, tuple[str, ...]] = {
    "GB": ("GB",),
    "IE": ("ALL",),
    "AU": ("NEM_TOTAL", "NSW1", "QLD1", "SA1", "TAS1", "VIC1"),
    "FR": ("FR",),
    "DE": ("DE",),
    "BE": ("BE",),
    "DK": ("DK",),
    "KZ": ("KZ", "KZ_W"),
}


def load_unit_series(market: str, unit: str, data_dir: Path | None = None) -> pd.Series:
    df = read_processed(market, data_dir)
    if unit == "NEM_TOTAL" and market == "AU":
        wide = (
            df.dropna(subset=["demand_mw"])
            .pivot_table(index="timestamp", columns="region", values="demand_mw")
            .dropna()
        )
        if wide.empty:
            raise IngestError(f"no aligned region data for {market}/{unit}")
        s = wide.sum(axis=1)
        return s[~s.index.duplicated(keep="last")]
    part = df[df.region == unit].dropna(subset=["demand_mw"])
    if part.empty:
        raise IngestError(f"no data for {market}/{unit}")
    s = part.set_index("timestamp")["demand_mw"].sort_index()
    return s[~s.index.duplicated(keep="last")]


def _fit_single(model_name: str, market: str, unit: str, hist: pd.Series):
    if model_name == "lightgbm":
        m = GBMModel(market, unit, use_weather=True)
    elif model_name == "ridge":
        m = RidgeModel(market, unit, use_weather=True)
    elif model_name == "naive":
        m = SeasonalNaive()
    else:
        raise ValueError(f"unknown {model_name}")
    m.fit(hist)
    return m


def _residual_anchors(last: pd.Timestamp, n: int = RESIDUAL_ANCHORS) -> list[pd.Timestamp]:
    # anchor at noon UTC like the backtests (a stable daily issue point)
    nxt = last.normalize() - pd.Timedelta(hours=12)
    return [nxt - pd.Timedelta(days=d) for d in range(n - 1, -1, -1)]


def _residual_predictions(
    market: str, unit: str, hist: pd.Series, model_name: str
) -> pd.Series:
    """Champion's 1..24h-ahead forecasts at the last rolling anchors vs actual."""
    out = []
    for anchor in _residual_anchors(hist.index[-1]):
        cutoff = hist.loc[:anchor]
        if len(cutoff) < MIN_HISTORY_POINTS:
            continue
        try:
            model = _fit_single(model_name, market, unit, cutoff)
            ts = pd.date_range(anchor + pd.Timedelta(hours=1), periods=24, freq="h")
            pred = model.predict(ts)
            act = hist.reindex(ts).astype("float64")
            out.append(pred.astype("float64") - act)
        except (ValueError, KeyError, pd.errors.InvalidIndexError) as exc:
            log.warning("residual %s/%s failed @%s: %s", model_name, unit, anchor, exc)
    return pd.concat(out) if out else pd.Series(dtype="float64")


def _ensemble_residuals(market: str, unit: str, hist: pd.Series) -> dict[str, pd.Series]:
    """Per-member residual series, computed ONCE per unit (weights and
    interval quantiles both read from this set — the E9 hot path used to
    refit every member twice per unit, measured ~2x the time it should)."""
    return {m: _residual_predictions(market, unit, hist, m) for m in ENSEMBLE_MEMBERS}


def _ensemble_weights(residuals: dict[str, pd.Series]) -> dict[str, float]:
    errs = {m: (abs(r).mean() if len(r) else None) for m, r in residuals.items()}
    valid = {m: e for m, e in errs.items() if e is not None and e > 0}
    if len(valid) < 2:
        return {m: 1.0 / len(ENSEMBLE_MEMBERS) for m in ENSEMBLE_MEMBERS}
    inv = {m: 1.0 / (e + EPS_MW) for m, e in valid.items()}
    z = sum(inv.values())
    return {m: inv.get(m, 0.0) / z for m in ENSEMBLE_MEMBERS}


def forecast_unit(
    market: str,
    unit: str,
    issue: pd.Timestamp,
    data_dir: Path | None = None,
    publish_hook=None,
) -> dict:
    full = load_unit_series(market, unit, data_dir)
    lag = pd.Timedelta(days=PUB_LAG_DAYS[market])
    cutoff = issue - lag
    hist_full = full.loc[:cutoff]
    if len(hist_full) < MIN_HISTORY_POINTS:
        raise IngestError(f"{market}/{unit}: published history too short at {issue}")
    hist = hist_full.loc[cutoff - pd.Timedelta(days=HISTORY_DAYS) :]

    champion = UNIT_CHAMPIONS.get(unit, CHAMPION_DEFAULT)
    step = CADENCE_MINUTES[market]
    start = hist_full.index[-1] + pd.Timedelta(minutes=step)
    targets = pd.date_range(
        start, start + pd.Timedelta(hours=HORIZON_H), freq=f"{step}min", tz="UTC"
    )[:-1]

    # future weather comes from the NWP forecast, NOT the archive
    w_future = unit_weather_forecast(unit, HORIZON_H + 48)

    def _predict(model, targets_):
        try:
            return model.predict(targets_, weather=w_future).astype("float64")
        except TypeError:
            return model.predict(targets_).astype("float64")

    if champion == "ensemble":
        residuals = _ensemble_residuals(market, unit, hist)
        weights = _ensemble_weights(residuals)
        pred = None
        for m in ENSEMBLE_MEMBERS:
            model = _fit_single(m, market, unit, hist)
            part = _predict(model, targets) * weights[m]
            pred = part if pred is None else pred.add(part, fill_value=0)
        # intervals from the weighted residual reconstruction over rolling anchors
        resid_signed = None
        for m in ENSEMBLE_MEMBERS:
            r = residuals[m] * weights[m]
            resid_signed = r if resid_signed is None else resid_signed.add(r, fill_value=0)
        resid_abs = resid_signed.abs() if resid_signed is not None else None
    else:
        weights = None
        model = _fit_single(champion, market, unit, hist)
        pred = _predict(model, targets)
        resid_abs = _residual_predictions(market, unit, hist, champion).abs()

    resid_abs = resid_abs.dropna() if resid_abs is not None else pd.Series(dtype="float64")
    qs = (
        {lv: float(resid_abs.quantile(lv / 100)) for lv in INTERVAL_LEVELS}
        if len(resid_abs) >= 20
        else {lv: None for lv in INTERVAL_LEVELS}
    )

    recent = hist_full.loc[hist_full.index[-1] - pd.Timedelta(days=2) :]
    points = []
    for ts, p in pred.items():
        row = {"t": ts.isoformat(), "pred": round(float(p), 1)}
        for lv in INTERVAL_LEVELS:
            q = qs[lv]
            row[f"lo{lv}"] = round(float(p) - q, 1) if q is not None else None
            row[f"hi{lv}"] = round(float(p) + q, 1) if q is not None else None
        points.append(row)
    return {
        "issue": issue.isoformat(),
        "market": market,
        "unit": unit,
        "champion": champion,
        "weights": {k: round(v, 4) for k, v in weights.items()} if weights else None,
        "data_through": str(hist_full.index[-1]),
        "horizon_h": HORIZON_H,
        "n_fit_points": len(hist),
        "published_demand_tail": [
            {"t": str(t), "v": round(float(v), 1)} for t, v in recent.items()
        ],
        "points": points,
    }


def run_forecast(
    units: list[tuple[str, str]] | None = None,
    issue: pd.Timestamp | None = None,
    data_dir: Path | None = None,
    site_dir: Path | None = None,
    snapshots_dir: Path | None = None,
) -> dict:
    issue = issue or pd.Timestamp(datetime.now(UTC))
    site_dir = site_dir or (REPO_ROOT / "site" / "data")
    snapshots_dir = snapshots_dir or (REPO_ROOT / "data" / "forecasts")
    if units is None:
        units = [(m, u) for m, us in MARKET_UNITS.items() for u in us]

    site_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(UTC).replace(microsecond=0).isoformat()

    snapshots = {}
    degraded = []
    for market, unit in units:
        try:
            snapshots[unit] = forecast_unit(market, unit, issue, data_dir)
            log.info("forecast %s/%s ok (%s)", market, unit, snapshots[unit]["champion"])
        except (IngestError, ValueError, KeyError) as exc:
            log.error("forecast %s/%s failed (graceful degrade): %s", market, unit, exc)
            degraded.append({"unit": unit, "error": str(exc)})

    latest_path = site_dir / "latest_forecasts.json"
    if latest_path.exists():
        try:
            prev = json.loads(latest_path.read_text(encoding="utf-8"))
            prev_units = prev.get("units", {})
        except (json.JSONDecodeError, TypeError):
            prev_units = {}
        merged_units = {**prev_units, **snapshots}
        prev_degraded = [d for d in prev.get("degraded", []) if d["unit"] not in snapshots]
        degraded = prev_degraded + degraded
    else:
        merged_units = snapshots

    from gridcast.eval.backtest import git_state as _gs
    from gridcast.publish.units_meta import UNITS_META

    writer_state = _gs(REPO_ROOT)
    latest = {
        "generated_at": generated,
        "generated_by": {
            # provenance of the writer itself; git_dirty exposed so the banner
            # chip cannot overclaim reproducibility (no clean-tree guard here)
            "git_sha": writer_state["git_sha"],
            "git_dirty": writer_state["git_dirty"],
            "gridcast_version": __import__("gridcast").__version__,
        },
        "issue": issue.isoformat(),
        "horizon_h": HORIZON_H,
        "units": merged_units,
        "units_meta": {u: UNITS_META[u] for u in merged_units if u in UNITS_META},
        "degraded": degraded,
    }
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    day = issue.date().isoformat()
    for unit, s in snapshots.items():
        (snapshots_dir / f"{day}_{unit}.json").write_text(
            json.dumps(s, ensure_ascii=False), encoding="utf-8"
        )
    _update_history(site_dir / "forecast_history.json", generated, snapshots)
    _write_metrics(site_dir / "metrics.json", generated, snapshots)
    _write_benchmark_extract(site_dir / "benchmark_extract.json")
    _write_ai_insights(site_dir / "ai_insights.json", latest)
    return latest


def _write_ai_insights(path: Path, latest: dict) -> None:
    """AI Analyst of the day (statistical by default, LLM optional w/ verify)."""
    try:
        from gridcast.publish.analyst import generate_insights

        metrics_doc = {}
        metrics_path = path.parent / "metrics.json"
        if metrics_path.exists():
            metrics_doc = json.loads(metrics_path.read_text(encoding="utf-8"))
        history_path = path.parent / "forecast_history.json"
        history_doc = json.loads(history_path.read_text(encoding="utf-8"))
        payload = generate_insights(latest, history_doc, metrics_doc)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        log.exception("ai-insights: generation failed, skipped")


def _load_benchmark() -> dict:
    bench_path = REPO_ROOT / "reports" / "latest_benchmark.json"
    if not bench_path.exists():
        return {}
    try:
        return json.loads(bench_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("benchmark json unreadable, skipped")
        return {}


def _write_metrics(path: Path, generated: str, snapshots: dict) -> None:
    """metrics.json v2: rolling-benchmark точность champion vs naive per unit
    + generated_by provenance (contract-additive; old keys unchanged)."""
    from gridcast.eval.backtest import git_state as _gs
    from gridcast.publish.units_meta import UNITS_META

    bench = _load_benchmark()
    units = {}
    for key, res in bench.get("results", {}).items():
        primary = res["primary_metric"]
        champ = res["champion_model"]
        units[key.split("/")[1]] = {
            "champion_model": champ,
            "primary_metric": primary,
            "champion_value": res["metrics"][champ]["overall"][primary],
            "naive_value": res["metrics"]["seasonal-naive-168h"]["overall"][primary],
        }
    payload = {
        "generated_at": generated,
        "generated_by": {
            **({"git_sha": bench.get("code", {}).get("git_sha")} if bench.get("code") else {}),
            "writer_git_sha": _gs(REPO_ROOT)["git_sha"],
            "writer_git_dirty": _gs(REPO_ROOT)["git_dirty"],
        },
        "units": units,
        "units_meta": {u: UNITS_META[u] for u in units if u in UNITS_META},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_benchmark_extract(path: Path) -> None:
    """Landing/explorer tables: by_horizon / by_month for each unit, clipped so
    the public bundle stays small (benchmark is MB-scale on disk)."""
    bench = _load_benchmark()
    if not bench:
        return
    units = {}
    for _key, res in bench.get("results", {}).items():
        unit = res["unit"]
        primary = res["primary_metric"]
        champ = res["champion_model"]
        m = res["metrics"][champ]
        n = res["metrics"].get("seasonal-naive-168h")
        n_h = (n or {}).get("by_horizon") or []
        n_m = (n or {}).get("by_month") or []
        units[unit] = {
            "champion_model": champ,
            "primary_metric": primary,
            "champion_value": m["overall"][primary],
            "naive_value": (n["overall"][primary] if n else None),
            "by_horizon": [
                {
                    "h": row["horizon_hours"],
                    "champion": row[primary],
                    "naive": (n_h[i][primary] if i < len(n_h) else None),
                }
                for i, row in enumerate(m["by_horizon"])
                if row["horizon_hours"] in (1.0, 6.0, 12.0, 24.0, 36.0, 48.0)
            ],
            "by_month": [
                {
                    "month": row["month"],
                    "champion": row[primary],
                    "naive": (n_m[i][primary] if i < len(n_m) else None),
                }
                for i, row in enumerate(m["by_month"])
            ],
            "conformal": res.get("conformal", {}).get("lightgbm-weather", {}).get("coverage"),
        }
    payload = {
        "generated_at": bench.get("generated_at"),
        "git_sha": (bench.get("code") or {}).get("git_sha"),
        "units": units,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _update_history(path: Path, generated: str, snapshots: dict) -> None:
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"days": []}
    entry = {
        "date": generated[:10],
        "units": {
            u: {
                "champion": s["champion"],
                "data_through": s["data_through"],
                "horizon_mean_mw": round(sum(p["pred"] for p in s["points"]) / len(s["points"]), 1),
                "points_short": s["points"][::4],  # sparse for the public bundle
            }
            for u, s in snapshots.items()
        },
    }
    keep = [d for d in history.get("days", []) if d.get("date") != entry["date"]][-60:]
    keep.append(entry)
    history["days"] = keep
    path.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
