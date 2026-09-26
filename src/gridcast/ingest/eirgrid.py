"""Ireland (All-Island SEM) — EirGrid Smart Grid Dashboard.

Verified 2026-09-26:
  The legacy JSON-RPC at /Dashboard/Svc is gone (404) and its CSV successor
  /DashboardService.svc/csv throttles aggressively (HTTP 503 after a couple of
  requests). The dashboard frontend itself is a Next.js app whose pages embed
  the chart data in the React Server Components flight payload; requesting the
  page with header "RSC: 1" returns the payload as text:

    GET https://www.smartgriddashboard.com/ALL/demand/?duration=week&datefrom=YYYY-MM-DD&dateto=YYYY-MM-DD
    -> ... "data":[{"date":"20-Sep-2026 00:00:00","actualDemand":4244,"forecastDemand":null},...]

  History back to at least 2019 confirmed. region=ALL is the All-Island
  system demand (the single electricity market is island-wide).

Timestamps in the payload are interval-start labels on a full 24h grid every
day of the year — including DST-change Sundays (verified on the 2026-03-29 and
2025-10-26 weeks, where Dublin wall time would lose/duplicate an hour). They
are therefore parsed as UTC directly.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import pandas as pd

from gridcast.ingest.base import (
    IngestError,
    fetch,
    make_session,
    normalize,
    save_raw,
    week_ranges,
)

log = logging.getLogger(__name__)

PAGE_URL = "https://www.smartgriddashboard.com/ALL/demand/"
RSC_HEADERS = {"RSC": "1"}
DATA_RE = re.compile(r'"data":\[')
MARKET = "IE"
REGION = "ALL"
SOURCE = "eirgrid"
PAUSE_S = 1.5  # polite pacing between weekly requests

_MONTHS = {
    mon: i + 1
    for i, mon in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
}
DATE_RE = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2})(?::(\d{2}))?$")


def _parse_local_stamp(stamp: str) -> pd.Timestamp:
    m = DATE_RE.match(stamp.strip())
    if not m:
        raise IngestError(f"EirGrid: unparseable timestamp {stamp!r}")
    day, mon, year, hh, mm, _ss = m.groups()
    month = _MONTHS.get(mon.title())
    if month is None:
        raise IngestError(f"EirGrid: unparseable month in {stamp!r}")
    return pd.Timestamp(int(year), month, int(day), int(hh), int(mm))


def extract_series(text: str) -> list[dict]:
    """Pull the demand series out of an RSC flight payload.

    The page embeds several "data":[...] arrays (yearly stats etc.); the demand
    chart series is the one whose items carry an 'actualDemand' field.
    """
    decoder = json.JSONDecoder()
    for match in DATA_RE.finditer(text):
        start = match.end() - 1  # position of '['
        try:
            obj, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "actualDemand" in obj[0]:
            return obj
    raise IngestError("EirGrid: no demand series ('actualDemand') found in RSC payload")


def parse_payload(text: str) -> pd.DataFrame:
    """Pure parser: RSC payload text -> (timestamp[UTC], demand_mw, forecast_mw)."""
    rows = extract_series(text)
    recs = []
    for row in rows:
        local_ts = _parse_local_stamp(str(row.get("date", "")))
        recs.append(
            (
                local_ts,
                float(row["actualDemand"]) if row.get("actualDemand") is not None else None,
                float(row["forecastDemand"]) if row.get("forecastDemand") is not None else None,
            )
        )
    if not recs:
        raise IngestError("EirGrid: demand series is empty")
    df = pd.DataFrame(recs, columns=["local_ts", "demand_mw", "forecast_mw"]).drop_duplicates(
        subset="local_ts", keep="first"
    )
    ts_utc = df["local_ts"].dt.tz_localize("UTC")
    out = pd.DataFrame(
        {
            "timestamp": ts_utc.reset_index(drop=True),
            "demand_mw": df["demand_mw"].reset_index(drop=True),
            "forecast_mw": df["forecast_mw"].reset_index(drop=True),
        }
    )
    return out[out["demand_mw"].notna() | out["forecast_mw"].notna()].reset_index(drop=True)


def fetch_week(session, start: date, end: date) -> str:
    content = fetch(
        session,
        PAGE_URL,
        params={
            "duration": "week",
            "datefrom": start.isoformat(),
            "dateto": end.isoformat(),
        },
        headers=RSC_HEADERS,
        timeout=120,
    )
    return content.decode("utf-8", errors="replace")


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = PAUSE_S):
    import time

    session = session or make_session()
    monday = start - pd.Timedelta(days=start.weekday())
    frames = []
    for w_start, w_end in week_ranges(monday, end):
        log.info("EirGrid: week %s .. %s", w_start, w_end)
        text = df = None
        for attempt in (1, 2):
            try:
                text = fetch_week(session, w_start, w_end)
                df = parse_payload(text)
                break
            except IngestError:
                log.warning("EirGrid: week %s attempt %d failed", w_start, attempt, exc_info=True)
                if attempt == 1:
                    time.sleep(5)
        if df is None:
            log.error("EirGrid: week %s .. %s skipped after retries", w_start, w_end)
            continue
        save_raw(SOURCE, f"demand_{w_start}_{w_end}.rsc.txt", text.encode(), raw_dir)
        df = df[
            (df["timestamp"] >= pd.Timestamp(start, tz="UTC"))
            & (df["timestamp"] < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
        ]
        frames.append(df)
        if pause_s and (w_end < end):
            time.sleep(pause_s)
    if not frames:
        raise IngestError(f"EirGrid: nothing downloaded for {start}..{end}")
    merged = pd.concat(frames, ignore_index=True).drop_duplicates(subset="timestamp", keep="first")
    return normalize(merged, MARKET, REGION, SOURCE)
