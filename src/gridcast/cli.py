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


def run_ingest(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gridcast ingest")
    parser.add_argument("--all", action="store_true", help="ingest all markets (default)")
    parser.add_argument("--market", nargs="+", choices=MARKETS, help="subset of markets")
    parser.add_argument(
        "--start",
        default=_default_start().isoformat(),
        help="first day (YYYY-MM-DD), default: 6 months back",
    )
    parser.add_argument("--end", default=date.today().isoformat(), help="last day (YYYY-MM-DD)")
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--out-dir", default=str(PROCESSED_DIR))
    args = parser.parse_args(argv)

    from pathlib import Path

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    markets = tuple(args.market) if args.market else MARKETS
    raw_dir, out_dir = Path(args.raw_dir), Path(args.out_dir)

    summaries, failed = [], []
    for market in markets:
        adapter = ADAPTERS[market]
        try:
            df = adapter.ingest(start, end, raw_dir=raw_dir)
            written = write_parquet(df, market, out_dir)
            summary = summarize(df, market)
            summary["parquet_files"] = len(written)
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

    report, _frames = run_backtest(markets, start, end, cfg, Path(args.data_dir))
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

    comparison = run_comparison(
        markets,
        start,
        end,
        models=tuple(args.models),
        refit_every_anchors=args.refit,
        chronos_stride=args.chronos_stride,
        data_dir=Path(args.data_dir),
    )
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "ingest":
        return run_ingest(argv[1:])
    if argv and argv[0] == "backtest":
        return run_backtest(argv[1:])
    if argv and argv[0] == "compare":
        return run_compare(argv[1:])
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
