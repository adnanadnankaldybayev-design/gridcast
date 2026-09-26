"""Great Britain — NESO open data portal (CKAN API).

Verified 2026-09-26:
  API root      https://api.neso.energy (data.neso.energy no longer resolves)
  dataset       historic-demand-data, one CSV resource per calendar year
  actuals lag   published ~21 days in arrears; provisional rows are flagged 'F'

Demand definition: ND (National Demand), MW. Settlement periods are elapsed
30-minute blocks from local midnight (Europe/London), so converting via local
midnight + (SP-1)*30min stays correct on 46/50-period DST days.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import date

import pandas as pd

from gridcast.ingest.base import (
    IngestError,
    fetch,
    make_session,
    midnight_utc,
    normalize,
    polite_sleep,
    save_raw,
)

log = logging.getLogger(__name__)

API_ROOT = "https://api.neso.energy"
DATASET = "historic-demand-data"
LOCAL_TZ = "Europe/London"
MARKET = "GB"
REGION = "GB"
SOURCE = "neso"


def resource_urls(session=None) -> dict[int, str]:
    """year -> CSV download URL, discovered live from the CKAN package."""
    session = session or make_session()
    url = f"{API_ROOT}/api/3/action/package_show"
    raw = fetch(session, url, params={"id": DATASET}, timeout=60)
    pkg = json.loads(raw)
    if not pkg.get("success"):
        raise IngestError(f"CKAN package_show({DATASET}) returned success=false")
    urls: dict[int, str] = {}
    for res in pkg["result"]["resources"]:
        name = res.get("name") or ""
        if name.startswith("Historic Demand Data") and res.get("format") == "CSV":
            try:
                year = int(name.rsplit(" ", 1)[1])
            except ValueError:
                continue
            urls[year] = res["url"]
    if not urls:
        raise IngestError(f"no yearly CSV resources found in dataset {DATASET}")
    return urls


def parse_csv(text: str) -> pd.DataFrame:
    """Pure parser: NESO yearly CSV text -> (timestamp[UTC], demand_mw, forecast_mw)."""
    raw = pd.read_csv(io.StringIO(text))
    required = {"SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "ND"}
    missing = required - set(raw.columns)
    if missing:
        raise IngestError(f"NESO CSV: unexpected columns, missing {sorted(missing)}")
    # Newer files flag provisional rows with 'F'; older files are actuals-only.
    if "FORECAST_ACTUAL_INDICATOR" in raw.columns:
        actual = raw[raw["FORECAST_ACTUAL_INDICATOR"] == "A"].copy()
    else:
        actual = raw.copy()
    actual = actual.dropna(subset=["ND"])
    dates = pd.to_datetime(actual["SETTLEMENT_DATE"], format="%Y-%m-%d").reset_index(drop=True)
    ts = midnight_utc(dates, LOCAL_TZ) + pd.to_timedelta(
        (actual["SETTLEMENT_PERIOD"].astype(int).reset_index(drop=True) - 1) * 30, unit="min"
    )
    return pd.DataFrame(
        {
            "timestamp": ts,
            "demand_mw": pd.to_numeric(actual["ND"].reset_index(drop=True), errors="coerce"),
            "forecast_mw": pd.NA,
        }
    ).dropna(subset=["demand_mw"])


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = 0.0):
    session = session or make_session()
    urls = resource_urls(session)
    frames = []
    for year in range(start.year, end.year + 1):
        if year not in urls:
            log.warning("NESO: no resource for year %s, skipped", year)
            continue
        log.info("NESO: downloading %s", urls[year])
        content = fetch(session, urls[year], timeout=300)
        save_raw(SOURCE, f"demanddata_{year}.csv", content, raw_dir)
        df = parse_csv(content.decode("utf-8"))
        df = df[
            (df["timestamp"] >= pd.Timestamp(start, tz="UTC"))
            & (df["timestamp"] < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
        ]
        frames.append(df)
        polite_sleep(pause_s)
    if not frames:
        raise IngestError(f"NESO: nothing downloaded for {start}..{end}")
    return normalize(pd.concat(frames, ignore_index=True), MARKET, REGION, SOURCE)
