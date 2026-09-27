"""Belgium — Elia open data ods003 (Elia grid load), no key.

Verified live 2026-09-27:
  GET https://opendata.elia.be/api/explore/v2.1/catalog/datasets/ods003/records
  fields: datetime (UTC ISO, e.g. "2026-09-26T21:45:00+00:00"), eliagridload (MW,
  15-min). Real-time publication, history from 2016. Daily UTC windows (96
  rows) keep paging trivial; values are grid load in MW.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pandas as pd

from gridcast.ingest.base import (
    IngestError,
    fetch,
    make_session,
    normalize,
    polite_sleep,
    save_raw,
)

log = logging.getLogger(__name__)

API = "https://opendata.elia.be/api/explore/v2.1/catalog/datasets/ods003/records"
MARKET = "BE"
REGION = "BE"
SOURCE = "elia"
PAUSE_S = 0.4


def _utc(ts_str: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts_str)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def parse_records(payload: str, window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    data = json.loads(payload)
    records = data.get("results")
    if records is None:
        raise IngestError(f"Elia: no 'results' in payload: {payload[:200]}")
    lo, hi = window
    rows = []
    for rec in records:
        ts_str = rec.get("datetime")
        if ts_str is None:
            raise IngestError(f"Elia: record without datetime: {sorted(rec)[:10]}")
        ts = _utc(ts_str)
        if lo <= ts < hi:
            load = rec.get("eliagridload")
            rows.append((ts, float(load) if load is not None else None, None))
    return pd.DataFrame(rows, columns=["timestamp", "demand_mw", "forecast_mw"])


def fetch_day(session, day: date) -> str:
    nxt = day + timedelta(days=1)
    return fetch(
        session,
        API,
        params={
            "select": "datetime,eliagridload",
            "where": f"datetime >= date'{day}' AND datetime < date'{nxt}'",
            "order_by": "datetime",
            "limit": 100,
        },
        timeout=90,
    ).decode("utf-8")


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = PAUSE_S):
    session = session or make_session()
    frames = []
    day = start
    while day <= end:
        try:
            text = fetch_day(session, day)
        except IngestError:
            log.exception("Elia: %s failed", day)
            day += timedelta(days=1)
            continue
        lo = pd.Timestamp(day, tz="UTC")
        df = parse_records(text, (lo, lo + pd.Timedelta(days=1)))
        if len(df):
            save_raw(SOURCE, f"ods003_{day}.json", text.encode(), raw_dir)
            frames.append(df)
        day += timedelta(days=1)
        polite_sleep(pause_s)
    if not frames:
        raise IngestError(f"Elia: nothing downloaded for {start}..{end}")
    merged = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset="timestamp", keep="first")
        .sort_values("timestamp")
    )
    return normalize(merged, MARKET, REGION, SOURCE)
