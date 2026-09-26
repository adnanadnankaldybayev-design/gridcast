"""gridcast CLI.

Usage: gridcast ingest [--all | --market GB IE ...] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime

import pandas as pd

from gridcast.config import MARKETS, PROCESSED_DIR, RAW_DIR
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "ingest":
        return run_ingest(argv[1:])
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
