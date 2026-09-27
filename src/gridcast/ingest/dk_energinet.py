"""Denmark — Energinet Energy Data Service (no key, HARSH rate limit).

Verified live 2026-09-27:
  meta catalog: https://api.energidataservice.dk/meta/dataset -> national
  hourly end-consumption is split across DK36/DK19 industry codes in
  `ConsumptionDK3619IndustryHour` (records per TimeUTC and industry code);
  national demand = SUM over codes per TimeUTC (Consumption_MWh == hourly
  MWh == average MW for the hour). TimeUTC is explicit UTC (DST-free).
  Latest available data at probe time: 2026-09-08 (~2.5 week publication lag —
  honestly reflected in the adapter's configurable pub lag).

  RATE LIMIT (measured): a burst of requests returns
  {"statusCode":429,"message":"Rate limit is exceeded. Try again in Ns"} — so
  this adapter fetches MONTH-sized windows in ONE request (limit high enough
  to hold all codes*hours), sleeps between requests, and honors the server's
  "Try again in Ns" with extra margin. Fetching a 7-month archive costs ~8
  requests and ~1 minute, not a burst.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

import pandas as pd

from gridcast.ingest.base import (
    IngestError,
    make_session,
    month_range,
    normalize,
    save_raw,
)

log = logging.getLogger(__name__)

API = "https://api.energidataservice.dk/dataset/ConsumptionDK3619IndustryHour"
MARKET = "DK"
REGION = "DK"
SOURCE = "energinet"
MIN_PAUSE_S = 3.0          # polite floor between successful requests
RATE_RE = re.compile(r"Try again in (\d+) seconds")
MAX_429_RETRIES = 6


def parse_records(payload: str) -> pd.DataFrame:
    data = json.loads(payload)
    if data.get("statusCode") == 429:
        raise RateLimited(payload)
    records = data.get("records")
    if records is None:
        raise IngestError(f"Energinet: no 'records' in payload: {payload[:200]}")
    rows = {}
    for rec in records:
        ts = rec.get("TimeUTC")
        value = rec.get("Consumption_MWh")
        if ts is None or value is None:
            continue
        t = pd.Timestamp(ts)
        t = t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")
        rows[t] = rows.get(t, 0.0) + float(value)
    out = pd.DataFrame(
        sorted(rows.items()), columns=["timestamp", "demand_mw"]
    )
    out["forecast_mw"] = None
    return out


class RateLimited(IngestError):
    """429 from Energinet; caller backs off honoring 'Try again in Ns'."""


def _wait_from(body: str, attempt: int) -> int:
    m = RATE_RE.search(body or "")
    return (int(m.group(1)) if m else 60) + attempt * 30 + 5


def fetch_month(session, ym: str) -> str:
    """One month with offset paging: a full month of DK36 industry rows
    (~33 codes/h, ~24k) exceeds the per-request limit; pages are pulled by
    offset until `total` is reached. 429 (HTTP or embedded) is retried with
    the server's own 'Try again in Ns' + margin."""
    start = pd.Timestamp(f"{ym}-01")
    end = start + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)
    page_size = 8000
    offset = 0
    all_records: list[dict] = []
    while True:  # stop when the server returns a short (final) page
        params = {
            "start": start.strftime("%Y-%m-%dT%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M"),
            "limit": str(page_size),
            "offset": str(offset),
            "timezone": "utc",
        }
        data = None
        for attempt in range(MAX_429_RETRIES):
            try:
                resp = session.get(API, params=params, timeout=180)
            except Exception as exc:
                raise IngestError(f"Energinet {ym}: network error {exc}") from exc
            if resp.status_code == 200:
                candidate = json.loads(resp.text)
                if candidate.get("statusCode") == 429:
                    wait = _wait_from(resp.text, attempt)
                    log.warning("Energinet %s: 429 in body, sleeping %ss", ym, wait)
                    time.sleep(wait)
                    continue
                data = candidate
                break
            wait = _wait_from(resp.text or "", attempt)
            log.warning("Energinet %s: HTTP %s, sleeping %ss", ym, resp.status_code, wait)
            time.sleep(wait)
        if data is None:
            raise IngestError(
                f"Energinet {ym}: rate limit persists after {MAX_429_RETRIES} retries"
            )
        records = data.get("records")
        if records is None:
            raise IngestError(f"Energinet {ym}: no 'records' in payload: {str(data)[:200]}")
        all_records.extend(records)
        offset += len(records)
        if len(records) < page_size or not records:
            break
        time.sleep(MIN_PAUSE_S)
    return json.dumps({"total": len(all_records), "records": all_records}, ensure_ascii=False)


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = MIN_PAUSE_S):
    session = session or make_session()
    frames = []
    for ym in month_range(start, end):
        log.info("Energinet: month %s", ym)
        try:
            text = fetch_month(session, ym)
        except IngestError:
            log.exception("Energinet: %s skipped", ym)
            continue
        save_raw(SOURCE, f"consumption_dk36_{ym}.json", text.encode(), raw_dir)
        df = parse_records(text)
        lo = pd.Timestamp(start, tz="UTC")
        hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        frames.append(df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)])
        time.sleep(MIN_PAUSE_S)
    if not frames:
        raise IngestError(f"Energinet: nothing downloaded for {start}..{end}")
    merged = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset="timestamp", keep="first")
        .sort_values("timestamp")
    )
    return normalize(merged, MARKET, REGION, SOURCE)
