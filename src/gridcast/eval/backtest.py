"""Rolling-origin backtest engine.

For every daily anchor (issue time `issue_hour_utc`) the model is fit ONLY on
data published by then (anchor minus the market's publication lag), then
predicts a full 48 h horizon. This mirrors the live daily job:

- no future data in fit history (engines must truncate, models are checked
  by a spy test),
- GB's 21-day publication lag is honored: a naive "last week" source that is
  not yet published is never used (the model's fallback handles it),
- the engine walks monthly parquet partitions; windows are configurable.

Metrics are aggregated overall, per horizon step, and per calendar month.
AU is evaluated per region and as the NEM-wide total (sum of regions on the
intersection of timestamps).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from gridcast.config import CADENCE_MINUTES, PROCESSED_DIR
from gridcast.eval.metrics import DEFAULT_MAPE_FLOOR_MW, summarize
from gridcast.ingest.base import read_processed
from gridcast.models.naive import SeasonalNaive

log = logging.getLogger(__name__)

# How old the freshest usable actual is at issue time (days).
# GB: NESO's own 21-day arrears. IE/AU dashboards are near-real-time; 6 h
# keeps the intraday current day safely out of fit history.
PUB_LAG_DAYS = {"GB": 21.0, "IE": 0.25, "AU": 0.25}

# Ratio metric of record per market. SA1 demand crosses zero at solar noon,
# so any *APE is meaningless there; MAE and sMAPE are the honest ones.
PRIMARY_METRIC = {"AU": "smape_pct", "GB": "mape_pct", "IE": "mape_pct"}

NEM_REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")


def min_lag_hours(market: str) -> int:
    from gridcast.features.build import MARKET_LAG_HOURS

    return min(MARKET_LAG_HOURS[market])


@dataclass
class BacktestConfig:
    step_hours: int = 24  # anchor cadence
    horizon_hours: int = 48  # SPEC H1: 24-48 h day-ahead horizon
    issue_hour_utc: int = 12
    train_days: int | None = None  # None = expanding window from data start
    pub_lag_days: dict[str, float] = field(default_factory=lambda: dict(PUB_LAG_DAYS))
    mape_floor_mw: float = DEFAULT_MAPE_FLOOR_MW
    model: str = "seasonal-naive-168h"
    # 1 = refit at every anchor (E2 protocol). >1 mirrors production periodic
    # retraining (e.g. weekly): leak-free, evaluation anchors unchanged.
    refit_every_anchors: int = 1
    # anchors with shorter published history are skipped; raise it when the
    # model needs real training depth (GBM warmup + fit). min_history_days is
    # converted per-market cadence and wins when set.
    min_history_points: int = 10
    min_history_days: float | None = None
    # warmup anchors: history shorter than this many market main-lag seasons;
    # they are flagged and also aggregated separately (post-warmup block)
    warmup_seasons: int = 2
    # anchor subsampling every Nth anchor (eval points only; leaks impossible).
    # Used by heavyweight models (Chronos zero-shot on CPU). Comparisons
    # always intersect on the COMMON anchor set across models.
    anchors_stride: int = 1

    def make_model(self, market: str, unit: str):
        """Model factories know the unit (calendar/weather config is per-unit).
        E7 scalability: registering a new market means adding its calendar and
        weather config rows; model code stays untouched."""
        if self.model == "seasonal-naive-168h":
            return SeasonalNaive(season_hours=168)
        if self.model in ("lightgbm-weather", "lightgbm-no-weather"):
            from gridcast.models.gbm import GBMModel

            return GBMModel(market, unit, use_weather=self.model == "lightgbm-weather")
        if self.model in ("ridge-weather", "ridge-no-weather"):
            from gridcast.models.ridge import RidgeModel

            return RidgeModel(market, unit, use_weather=self.model == "ridge-weather")
        if self.model == "chronos-bolt-zero-shot":
            from gridcast.models.chronos import ChronosModel

            return ChronosModel(market, unit)
        raise ValueError(f"unknown model {self.model!r}")


def load_series(
    market: str, data_dir: Path | None = None
) -> dict[str, pd.Series]:
    """unit -> demand series (UTC, MW). AU gets per-region + NEM_TOTAL."""
    df = read_processed(market, data_dir)
    if df.empty:
        raise FileNotFoundError(f"no processed data for market {market}")
    df = df.dropna(subset=["demand_mw"])
    out = {}
    for unit, part in df.groupby("region"):
        series = part.set_index("timestamp")["demand_mw"].sort_index()
        series = series[~series.index.duplicated(keep="last")]
        out[unit] = series
    if market == "AU" and len(out) > 1:
        aligned = pd.concat({r: out[r] for r in sorted(out) if r in NEM_REGIONS}, axis=1)
        out["NEM_TOTAL"] = aligned.sum(axis=1, min_count=len(NEM_REGIONS)).dropna()
    return out


def anchors_for(
    series: pd.Series, start: pd.Timestamp, end: pd.Timestamp, cfg: BacktestConfig
) -> pd.DatetimeIndex:
    step = pd.Timedelta(hours=cfg.step_hours)
    first = series.index[0] + pd.Timedelta(days=1)  # at least a day of history
    anchor = max(first, start).normalize() + pd.Timedelta(hours=cfg.issue_hour_utc)
    last = min(end, series.index[-1] - pd.Timedelta(hours=cfg.horizon_hours))
    out = []
    while anchor <= last:
        if anchor >= first:
            out.append(anchor)
        anchor += step
    stride = max(1, cfg.anchors_stride)
    return pd.DatetimeIndex(out)[::stride]


def rolling_origin(
    series: pd.Series,
    unit: str,
    market: str,
    cfg: BacktestConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Long-form backtest frame: one row per (anchor, forecast timestamp)."""
    step_min = CADENCE_MINUTES[market]
    lag = pd.Timedelta(days=cfg.pub_lag_days[market])
    rows = []
    model = None
    fits = 0
    for i, anchor in enumerate(anchors_for(series, start, end, cfg)):
        cutoff = anchor - lag
        history = series.loc[:cutoff]
        if cfg.train_days is not None:
            history = history.loc[cutoff - pd.Timedelta(days=cfg.train_days) :]
        min_pts = cfg.min_history_points
        if cfg.min_history_days is not None:
            min_pts = max(min_pts, int(cfg.min_history_days * 1440 / step_min))
        if len(history) < min_pts:
            log.warning(
                "%s/%s anchor %s: history %d < %d, skipped",
                market,
                unit,
                anchor,
                len(history),
                min_pts,
            )
            continue
        targets = pd.date_range(
            anchor + pd.Timedelta(minutes=step_min),
            anchor + pd.Timedelta(hours=cfg.horizon_hours),
            freq=f"{step_min}min",
        )
        actual = series.reindex(targets)
        if model is None or i % cfg.refit_every_anchors == 0:
            model = cfg.make_model(market, unit)
            model.fit(history)
            fits += 1
        elif hasattr(model, "update_history"):
            # production-style periodic retraining: parameters frozen since the
            # last refit, but the lag lookup window is this anchor's published
            # past — leak-free by the same cutoff argument
            model.update_history(history)
        predicted = model.predict(targets)
        valid = actual.notna()
        if not valid.all():
            log.debug(
                "%s/%s anchor %s: %d horizon points missing upstream",
                market,
                unit,
                anchor,
                (~valid).sum(),
            )
        warmup = (cutoff - series.index[0]) < pd.Timedelta(
            hours=cfg.warmup_seasons * min_lag_hours(market)
        )
        rows.append(
            pd.DataFrame(
                {
                    "anchor": anchor,
                    "timestamp": targets[valid],
                    "horizon_hours": (targets[valid] - anchor) / pd.Timedelta(hours=1),
                    "actual": actual[valid],
                    "predicted": predicted[valid],
                    "warmup": warmup,
                }
            )
        )
    if not rows:
        raise ValueError(f"{market}/{unit}: no anchors in [{start}, {end}]")
    return pd.concat(rows, ignore_index=True)


def aggregate(bt: pd.DataFrame, cfg: BacktestConfig) -> dict:
    floor = cfg.mape_floor_mw
    overall = summarize(bt["actual"], bt["predicted"], floor)
    by_horizon = [
        {"horizon_hours": float(h), **summarize(g["actual"], g["predicted"], floor)}
        for h, g in bt.groupby("horizon_hours")
    ]
    by_month = [
        {"month": str(m), **summarize(g["actual"], g["predicted"], floor)}
        for m, g in bt.groupby(bt["timestamp"].dt.strftime("%Y-%m"))
    ]
    out = {"overall": overall, "by_horizon": by_horizon, "by_month": by_month}
    if "warmup" in bt.columns:
        post = bt[~bt["warmup"]]
        warmup_anchors = int(bt[bt["warmup"]]["anchor"].nunique())
        out["warmup_anchors"] = warmup_anchors
        out["n_anchors_total"] = int(bt["anchor"].nunique())
        if len(post):
            out["overall_post_warmup"] = summarize(post["actual"], post["predicted"], floor)
            out["post_warmup_share"] = round(len(post) / len(bt), 4)
    return out


def run_backtest(
    markets: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    cfg: BacktestConfig | None = None,
    data_dir: Path | None = None,
    series_override: dict[str, dict[str, pd.Series]] | None = None,
) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Returns (report, {market/unit: long-form frame}). `series_override` lets
    tests run the engine without touching data/."""
    cfg = cfg or BacktestConfig()
    data_dir = data_dir or PROCESSED_DIR
    results, frames = {}, {}
    for market in markets:
        units = (
            series_override[market] if series_override else load_series(market, data_dir)
        )
        for unit, series in units.items():
            bt = rolling_origin(series, unit, market, cfg, start, end)
            agg = aggregate(bt, cfg)
            key = f"{market}/{unit}"
            frames[key] = bt
            results[market] = results.get(market, {})
            results[market][unit] = {
                **agg,
                "primary_metric": PRIMARY_METRIC[market],
                "pub_lag_days": cfg.pub_lag_days[market],
                "n_anchors": int(bt["anchor"].nunique()),
                "cadence_min": CADENCE_MINUTES[market],
            }
    report = {
        "model": cfg.model,
        "config": asdict(cfg),
        "period": {"start": str(start), "end": str(end)},
        "results": results,
    }
    return report, frames


def git_state(repo_root: Path) -> dict:
    """(sha, dirty) of the repo that produced the artifacts. Fail-loud: a
    report with unknown provenance is worse than no report."""
    import subprocess

    def run(*args) -> str:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )
        return proc.stdout.strip()

    try:
        return {
            "git_sha": run("rev-parse", "--short", "HEAD"),
            "git_dirty": bool(run("status", "--porcelain")),
        }
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(f"cannot stamp report: git failed in {repo_root}: {exc}") from exc


def assert_clean_tree(repo_root: Path) -> None:
    """Trust policy: artifacts are only written from a reproducible commit."""
    state = git_state(repo_root)
    if state["git_dirty"]:
        raise RuntimeError(
            "working tree is dirty — commit first (or pass --allow-dirty) so the "
            "report's git SHA reproducibly matches its code"
        )


def finish_report(report: dict, out_path: Path, repo_root: Path | None = None) -> dict:
    """Stamp provenance (time, git, version) and persist."""
    import json
    from datetime import UTC, datetime

    from gridcast import __version__
    from gridcast.config import REPO_ROOT

    report["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    report["code"] = {"gridcast_version": __version__, **git_state(repo_root or REPO_ROOT)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
