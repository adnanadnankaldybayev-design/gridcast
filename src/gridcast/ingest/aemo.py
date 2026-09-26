"""Australian NEM — AEMO monthly "price and demand" CSV per region.

Verified 2026-09-26:
  GET https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_YYYYMM_{REGION}.csv
  regions: NSW1 QLD1 SA1 TAS1 VIC1; history back to at least 2015.
  (nemweb.com.au now redirects to aemo.com.au; the MMSDM zip archives under
  www.nemweb.com.au/Data_Archive/... are far heavier than this endpoint.)

SETTLEMENTDATE is NEM market time: fixed UTC+10 (Australia/Brisbane), no DST.
TOTALDEMAND is in MW per 5-minute dispatch interval.
"""

from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

from gridcast.ingest.base import (
    IngestError,
    fetch,
    make_session,
    month_range,
    normalize,
    save_raw,
)

log = logging.getLogger(__name__)

BASE_URL = "https://www.aemo.com.au/aemo/data/nem/priceanddemand"
NEM_REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
MARKET_TZ = "Australia/Brisbane"  # fixed UTC+10, NEM market time has no DST
MARKET = "AU"
SOURCE = "aemo"
PAUSE_S = 0.5


def parse_csv(text: str, region: str) -> pd.DataFrame:
    """Pure parser: AEMO monthly CSV text -> (timestamp[UTC], demand_mw, forecast_mw)."""
    raw = pd.read_csv(io.StringIO(text))
    required = {"REGION", "SETTLEMENTDATE", "TOTALDEMAND"}
    missing = required - set(raw.columns)
    if missing:
        raise IngestError(f"AEMO CSV: unexpected columns, missing {sorted(missing)}")
    raw = raw[raw["REGION"] == region]
    naive = pd.to_datetime(raw["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S")
    ts = naive.dt.tz_localize(MARKET_TZ).dt.tz_convert("UTC").reset_index(drop=True)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "demand_mw": pd.to_numeric(raw["TOTALDEMAND"].reset_index(drop=True), errors="coerce"),
            "forecast_mw": pd.NA,
        }
    ).dropna(subset=["demand_mw"])


def ingest(
    start: date,
    end: date,
    *,
    raw_dir=None,
    session=None,
    regions: tuple[str, ...] = NEM_REGIONS,
    pause_s: float = PAUSE_S,
):
    session = session or make_session()
    frames = []
    for ym in month_range(start, end):
        y, m = ym.split("-")
        for region in regions:
            url = f"{BASE_URL}/PRICE_AND_DEMAND_{y}{m}_{region}.csv"
            log.info("AEMO: %s %s", ym, region)
            content = fetch(session, url, timeout=120)
            save_raw(SOURCE, f"price_and_demand_{y}{m}_{region}.csv", content, raw_dir)
            df = parse_csv(content.decode("utf-8"), region)
            df["region"] = region
            frames.append(df)
            if pause_s:
                import time

                time.sleep(pause_s)
    if not frames:
        raise IngestError(f"AEMO: nothing downloaded for {start}..{end}")
    merged = pd.concat(frames, ignore_index=True)
    merged = merged[
        (merged["timestamp"] >= pd.Timestamp(start, tz="UTC"))
        & (merged["timestamp"] < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
    ]
    # normalize() stamps a single region column; AU carries five, so assemble manually.
    normalized = []
    for region, part in merged.groupby("region"):
        normalized.append(normalize(part.drop(columns="region"), MARKET, region, SOURCE))
    return pd.concat(normalized, ignore_index=True)
