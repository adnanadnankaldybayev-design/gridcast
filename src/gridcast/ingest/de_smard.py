"""Germany — SMARD (Bundesnetzagentur) Netzlast chart API, no key.

Verified live 2026-09-27:
  two-step API:
  1. GET https://www.smard.de/app/chart_data/410/DE/index_quarterhour.json
     -> {"timestamps":[epoch_ms, ...]} weekly partition ids (from 2014-12)
  2. GET https://www.smard.de/app/chart_data/410/DE/410_DE_quarterhour_{ts}.json
     -> {"series_name":..., "series":[[epoch_ms, value], ...]}

  UNIT WARNING (newcomer trap, now pinned by a contract test): values are
  ENERGY in MWh per 15-minute interval (stated in SMARD's own UI), i.e.
  average power MW = value * 4. Verified against recent values
  (~14-20 GWh/quarter-hour -> 56-80 GW average, the German power demand).

Filter 410 = Netzlast (system load Germany).
"""

from __future__ import annotations

import json
import logging
from datetime import date

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

INDEX_URL = "https://www.smard.de/app/chart_data/410/DE/index_quarterhour.json"
WEEK_URL = "https://www.smard.de/app/chart_data/410/DE/410_DE_quarterhour_{ts}.json"
MARKET = "DE"
REGION = "DE"
SOURCE = "smard"
PAUSE_S = 0.8


def get_index(session) -> list[int]:
    return json.loads(fetch(session, INDEX_URL, timeout=60))["timestamps"]


def parse_week(payload: str, window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    data = json.loads(payload)
    series = data.get("series")
    if series is None:
        raise IngestError(f"SMARD: no 'series' key: {payload[:200]}")
    lo, hi = window
    rows = []
    for ts_ms, value in series:
        ts = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC")
        if ts < lo or ts >= hi:
            continue
        rows.append((ts, float(value) * 4.0 if value is not None else None, None))  # MWh->MW
    return pd.DataFrame(rows, columns=["timestamp", "demand_mw", "forecast_mw"])


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = PAUSE_S):
    session = session or make_session()
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    frames = []
    for ts in get_index(session):
        week_start = pd.Timestamp(ts, unit="ms", tz="UTC")
        if week_start >= hi or week_start + pd.Timedelta(days=7) <= lo:
            continue
        url = WEEK_URL.format(ts=ts)
        try:
            payload = fetch(session, url, timeout=120).decode("utf-8")
        except IngestError:
            log.exception("SMARD: week %s failed", week_start.date())
            continue
        save_raw(SOURCE, f"410_de_{ts}.json", payload.encode(), raw_dir)
        df = parse_week(payload, (lo, hi))
        if len(df):
            frames.append(df)
        polite_sleep(pause_s)
    if not frames:
        raise IngestError(f"SMARD: nothing downloaded for {start}..{end}")
    merged = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset="timestamp", keep="first")
        .sort_values("timestamp")
    )
    return normalize(merged, MARKET, REGION, SOURCE)
