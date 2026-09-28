"""gridcast CLI.

Usage:
  gridcast ingest   [--all | --market GB IE ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
  gridcast backtest [--market GB IE ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [options]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from gridcast.config import MARKETS, PROCESSED_DIR, RAW_DIR, REPO_ROOT
from gridcast.ingest import ADAPTERS
from gridcast.ingest.base import IngestError, summarize, write_parquet

log = logging.getLogger("gridcast")


def _default_start() -> date:
    first = date.today().replace(day=1)
    return (pd.Timestamp(first) - pd.DateOffset(months=6)).date()


def _incremental_start(market: str, out_dir, default_start: date) -> date:
    """Daily-driver start: if a market already has processed data, begin at
    its last timestamp minus a 2-day overlap (re-reads only the fresh tail —
    this is what keeps the CI ingest under a few minutes on a warm cache)."""
    from gridcast.ingest.base import read_processed

    df = read_processed(market, out_dir)
    if df.empty:
        return default_start
    last = df["timestamp"].max().date()
    return max(default_start, last - pd.Timedelta(days=2))


def run_ingest(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gridcast ingest")
    parser.add_argument("--all", action="store_true", help="ingest all markets (default)")
    parser.add_argument("--market", nargs="+", choices=MARKETS, help="subset of markets")
    parser.add_argument(
        "--start",
        default=None,
        help="first day (YYYY-MM-DD); default: incremental from existing data",
    )
    parser.add_argument("--end", default=date.today().isoformat(), help="last day (YYYY-MM-DD)")
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(PROCESSED_DIR))
    args = parser.parse_args(argv)

    from pathlib import Path

    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    markets = tuple(args.market) if args.market else MARKETS
    raw_dir, out_dir = Path(args.raw_dir), Path(args.out_dir)
    default_start = (
        datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.start
        else _default_start()
    )

    summaries, failed = [], []
    for market in markets:
        adapter = ADAPTERS[market]
        start = (
            default_start
            if args.start
            else _incremental_start(market, out_dir, default_start)
        )
        try:
            df = adapter.ingest(start, end, raw_dir=raw_dir)
            written = write_parquet(df, market, out_dir)
            summary = summarize(df, market)
            summary["parquet_files"] = len(written)
            summary["start"] = str(start)
            summaries.append(summary)
        except IngestError:
            log.exception("market %s failed", market)
            failed.append(market)

    import json

    print(json.dumps({"ok": not failed, "failed": failed, "markets": summaries}, indent=2))
    return 1 if failed else 0


def _tree_guard(allow_dirty: bool) -> None:
    if allow_dirty:
        return
    from gridcast.eval.backtest import assert_clean_tree

    try:
        assert_clean_tree(REPO_ROOT)
    except RuntimeError as exc:
        print(f"refusing to write report: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def run_backtest(argv: list[str]) -> int:
    from gridcast.eval.backtest import BacktestConfig, finish_report, run_backtest

    parser = argparse.ArgumentParser(prog="gridcast backtest")
    parser.add_argument("--market", nargs="+", choices=MARKETS, help="default: all")
    parser.add_argument("--start", default="2026-03-01", help="anchor window start (YYYY-MM-DD)")
    parser.add_argument(
        "--end", default=date.today().isoformat(), help="anchor window end (YYYY-MM-DD)"
    )
    parser.add_argument("--issue-hour", type=int, default=12, help="anchor hour UTC")
    parser.add_argument("--step-hours", type=int, default=24)
    parser.add_argument("--horizon-hours", type=int, default=48)
    parser.add_argument("--train-days", type=int, default=None, help="omit = expanding window")
    parser.add_argument(
        "--model",
        default="seasonal-naive-168h",
        choices=[
            "seasonal-naive-168h",
            "ridge-weather",
            "ridge-no-weather",
            "lightgbm-weather",
            "lightgbm-no-weather",
            "chronos-bolt-zero-shot",
        ],
    )
    parser.add_argument("--data-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "reports"))
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="write the report even from a dirty tree (SHA no longer guarantees the code)",
    )
    args = parser.parse_args(argv)
    _tree_guard(args.allow_dirty)

    cfg = BacktestConfig(
        step_hours=args.step_hours,
        horizon_hours=args.horizon_hours,
        issue_hour_utc=args.issue_hour,
        train_days=args.train_days,
        model=args.model,
    )
    markets = tuple(args.market) if args.market else MARKETS
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)

    try:
        report, _frames = run_backtest(markets, start, end, cfg, Path(args.data_dir))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out_dir) / f"backtest_{cfg.model}_{stamp}.json"
    report = finish_report(report, out_path)

    rows = []
    for market, units in report["results"].items():
        for unit, res in units.items():
            key = res["primary_metric"]
            rows.append(
                {
                    "unit": f"{market}/{unit}",
                    "primary": f"{key}={res['overall'][key]}",
                    "mae_mw": res["overall"]["mae_mw"],
                    "n": res["overall"]["n"],
                    "anchors": res["n_anchors"],
                }
            )
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"report: {out_path}")
    return 0


def run_compare(argv: list[str]) -> int:
    from gridcast.eval.backtest import finish_report
    from gridcast.eval.compare import (
        DEFAULT_MODELS,
        model_verdicts,
        render_markdown,
        run_comparison,
    )

    parser = argparse.ArgumentParser(prog="gridcast compare")
    parser.add_argument("--market", nargs="+", choices=MARKETS, help="default: all")
    parser.add_argument("--start", default="2026-03-01", help="anchor window start")
    parser.add_argument("--end", default=date.today().isoformat(), help="anchor window end")
    parser.add_argument(
        "--refit", type=int, default=7, help="GBM refit cadence in anchors (production-style)"
    )
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument(
        "--chronos-stride",
        type=int,
        default=6,
        help="evaluate Chronos every Nth anchor (6 rotates weekdays; CPU budget guard)",
    )
    parser.add_argument("--data-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "reports"))
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="write the report even from a dirty tree",
    )
    args = parser.parse_args(argv)
    _tree_guard(args.allow_dirty)

    markets = tuple(args.market) if args.market else MARKETS
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)

    try:
        comparison = run_comparison(
            markets,
            start,
            end,
            models=tuple(args.models),
            refit_every_anchors=args.refit,
            chronos_stride=args.chronos_stride,
            data_dir=Path(args.data_dir),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_json = Path(args.out_dir) / f"model_zoo_{stamp}.json"
    report = {
        "comparison": comparison,
        "refit_every_anchors": args.refit,
        "chronos_stride": args.chronos_stride,
        "models": list(args.models),
    }
    finish_report(report, out_json)
    out_md = out_json.with_suffix(".md")
    out_md.write_text(
        render_markdown(
            comparison,
            (args.start, args.end),
            {"refit_every_anchors": args.refit, "chronos_stride": args.chronos_stride},
        ),
        encoding="utf-8",
    )
    for key, v in model_verdicts(comparison).items():
        for model, entry in v["models"].items():
            log.info(
                "%s: %s=%s vs naive %s (beats=%s)",
                key,
                model,
                entry["value"],
                v["naive"],
                entry["beats_naive"],
            )
    print(f"json: {out_json}\nmd:   {out_md}")
    return 0


def run_forecast(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gridcast forecast")
    parser.add_argument("--unit", nargs="+", help="limit units (e.g. GB FR KZ)")
    parser.add_argument("--data-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--site-dir", default=str(REPO_ROOT / "site" / "data"))
    parser.add_argument("--snapshots-dir", default=str(REPO_ROOT / "data" / "forecasts"))
    args = parser.parse_args(argv)

    from gridcast.publish.forecast import MARKET_UNITS, run_forecast

    wanted = set(args.unit or [])
    units = [
        (m, u)
        for m, us in MARKET_UNITS.items()
        for u in us
        if not wanted or u in wanted
    ]
    latest = run_forecast(
        units,
        data_dir=Path(args.data_dir),
        site_dir=Path(args.site_dir),
        snapshots_dir=Path(args.snapshots_dir),
    )
    print(
        f"issued {len(latest['units'])} unit forecasts -> {args.site_dir}/latest_forecasts.json"
    )
    if latest["degraded"]:
        print(f"degraded: {latest['degraded']}", file=sys.stderr)
    return 0


def run_ablation(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gridcast ablation nwp")
    parser.add_argument("kind", choices=["nwp"])
    parser.add_argument("--start", default="2026-08-20")
    parser.add_argument("--end", default="2026-09-20")
    parser.add_argument(
        "--sigma", type=float, default=1.75, help="degrees C of day-ahead NWP noise"
    )
    parser.add_argument("--units", nargs="+", default=["GB/GB", "IE/ALL", "DE/DE"])
    parser.add_argument("--data-dir", default=str(PROCESSED_DIR))
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "reports" / "latest_nwp_ablation.json")
    )
    args = parser.parse_args(argv)

    from gridcast.eval.backtest import finish_report
    from gridcast.eval.nwp_ablation import run_nwp_ablation

    def mape(frame):
        a = frame.actual.astype(float)
        p = frame.predicted.astype(float)
        return float((100 * (a - p).abs() / a.abs()).mean())

    pairs = []
    for u in args.units:
        market, unit = u.split("/")
        pairs.append((market, unit))
    res = run_nwp_ablation(
        pairs,
        pd.Timestamp(args.start, tz="UTC"),
        pd.Timestamp(args.end, tz="UTC"),
        sigma=args.sigma,
        data_dir=Path(args.data_dir),
    )
    report = {
        "experiment": (
            f"archive-weather vs ~N(0, sigma={args.sigma:.2f}C)-degraded weather "
            "(GBM-weather)"
        ),
        "sigma_c": args.sigma,
        "window": {"start": args.start, "end": args.end},
        "note": "a finite-sample seed realization; DE is the small-window near-zero counterexample",
        "results": {
            key: {
                "anchors": int(pair["archive"][1].anchor.nunique()),
                "mape_archive": round(mape(pair["archive"][1]), 3),
                "mape_noisy": round(mape(pair["noisy"][1]), 3),
                "delta_pp": round(mape(pair["noisy"][1]) - mape(pair["archive"][1]), 3),
            }
            for key, pair in res.items()
        },
    }
    finish_report(report, Path(args.out))
    for key, r in report["results"].items():
        log.info(
            "%s: archive %.3f -> noisy %.3f (delta %+.3f)",
            key, r["mape_archive"], r["mape_noisy"], r["delta_pp"],
        )
    print(f"wrote {args.out}")
    return 0


def run_analyze(argv: list[str]) -> int:
    from gridcast.eval.analyze import run_analysis
    from gridcast.eval.backtest import finish_report
    from gridcast.eval.benchmark import render_benchmark

    parser = argparse.ArgumentParser(prog="gridcast analyze")
    parser.add_argument("--market", nargs="+", choices=MARKETS, help="default: all")
    parser.add_argument("--start", default="2026-03-01", help="anchor window start")
    parser.add_argument("--end", default=date.today().isoformat(), help="anchor window end")
    parser.add_argument("--anchors-stride", type=int, default=6)
    parser.add_argument(
        "--refit",
        type=int,
        default=2,
        help="GBM/ridge refit every Nth strided anchor (2 at stride 6 ≈ 12 days)",
    )
    parser.add_argument("--data-dir", default=str(PROCESSED_DIR))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "reports"))
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="write the report even from a dirty tree",
    )
    args = parser.parse_args(argv)
    _tree_guard(args.allow_dirty)

    markets = tuple(args.market) if args.market else MARKETS
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)

    report = run_analysis(
        markets,
        start,
        end,
        anchors_stride=args.anchors_stride,
        refit_every_anchors=args.refit,
        data_dir=Path(args.data_dir),
    )
    out_dir = Path(args.out_dir)
    finish_report(report, out_dir / "latest_benchmark.json")
    md = render_benchmark(report)
    (out_dir / "latest_benchmark.md").write_text(md, encoding="utf-8")
    (out_dir / "BENCHMARK.md").write_text(md, encoding="utf-8")
    for key, res in report["results"].items():
        primary = res["primary_metric"]
        log.info(
            "%s champion=%s (%s=%s)",
            key,
            res["champion_model"],
            primary,
            res["metrics"][res["champion_model"]]["overall"][primary],
        )
    print(f"json: {out_dir / 'latest_benchmark.json'}\ncard: {out_dir / 'BENCHMARK.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "ingest":
        return run_ingest(argv[1:])
    if argv and argv[0] == "backtest":
        return run_backtest(argv[1:])
    if argv and argv[0] == "compare":
        return run_compare(argv[1:])
    if argv and argv[0] == "analyze":
        return run_analyze(argv[1:])
    if argv and argv[0] == "forecast":
        return run_forecast(argv[1:])
    if argv and argv[0] == "ablation":
        return run_ablation(argv[1:])
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
