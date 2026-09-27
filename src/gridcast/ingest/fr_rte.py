"""France — RTE éCO2mix national consumption (Opendatasoft, no key).

Verified live 2026-09-27:
  records API of TWO datasets (history is split between them!):
  - eco2mix-national-cons-def  (definitive archive; last record at probe time:
    2026-06-30 21:45 UTC — refreshed in batches, months behind)
  - eco2mix-national-tr        (rolling real-time, retention ~90 days)
  Combined they cover our full window; the adapter merges + dedups on
  timestamp (cons-def preferred on overlap — it is the corrected series).

  Fields: date_heure (UTC, e.g. "2026-06-30T21:45:00+00:00" — local
  date='2026-06-30', heure='23:45' == UTC+2 CEST, confirmed), consommation
  (MW, 15-min, may be null in placeholders), prevision_j1 (RTE's own J-1
  forecast — kept as forecast_mw for a future operator benchmark).

Paging: ODS records API caps offset+limit~10k; we walk UTC-day windows
(96 rows/day, one request when possible) so the cap never binds.
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

DATASETS = (
    ("eco2mix-national-cons-def", "historic"),
    ("eco2mix-national-tr", "rolling"),
)
API = "https://odre.opendatasoft.com/api/v2/catalog/datasets/{ds}/records"
SELECT = "date_heure,consommation,prevision_j1"
PLACEHOLDER_MIN = -1.0  # consommation may be null in not-yet-filled slots
MARKET = "FR"
REGION = "FR"
SOURCE = "rte"
PAUSE_S = 1.0  # ODRE has brittle rate quotas; day-walk must stay polite


def record_url(ds: str) -> str:
    return API.format(ds=ds)


def parse_records(payload: str, window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    data = json.loads(payload)
    records = data.get("records")
    if records is None:
        raise IngestError(f"RTE: no 'records' in payload: {payload[:200]}")
    rows = []
    for rec in records:
        fields = rec.get("record", {}).get("fields", {})
        ts = fields.get("date_heure")
        cons = fields.get("consommation")
        if ts is None:
            raise IngestError(f"RTE: record without date_heure: {sorted(fields)[:12]}")
        rows.append(
            (
                pd.Timestamp(ts),
                float(cons) if cons is not None else None,
                float(fields["prevision_j1"]) if fields.get("prevision_j1") is not None else None,
            )
        )
    df = pd.DataFrame(rows, columns=["timestamp", "demand_mw", "forecast_mw"])
    if df.empty:
        return df
    ts = df["timestamp"]
    df["timestamp"] = (
        ts.dt.tz_convert("UTC") if ts.dt.tz is not None else ts.dt.tz_localize("UTC")
    )
    # the definitive file duplicates DST-shift hours (+ rows with null
    # consommation): keep one row per timestamp, prefer a non-null demand
    df = (
        df.assign(_has_demand=df["demand_mw"].notna())
        .sort_values(["timestamp", "_has_demand"], ascending=[True, False])
        .drop_duplicates(subset="timestamp", keep="first")
        .drop(columns="_has_demand")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    lo, hi = window
    return df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)].reset_index(drop=True)


def fetch_day(session, ds: str, day: date) -> str:
    nxt = day + timedelta(days=1)
    return fetch(
        session,
        record_url(ds),
        params={
            "select": SELECT,
            "order_by": "date_heure",
            # ODRE rejects a capital 'AND' in the where ODSQL (HTTP 400)
            "where": f"date_heure >= date'{day}' and date_heure < date'{nxt}'",
            "limit": 200,  # DST days duplicate local hours above the 96/day base
        },
        timeout=90,
    ).decode("utf-8")


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = PAUSE_S):
    session = session or make_session()
    frames = []
    for ds, kind in DATASETS:
        got_any = False
        day = start
        while day <= end:
            try:
                text = fetch_day(session, ds, day)
            except IngestError:
                log.exception("RTE %s %s: fetch failed", ds, day)
                day += timedelta(days=1)
                continue
            lo, hi = pd.Timestamp(day, tz="UTC"), pd.Timestamp(day + timedelta(days=1), tz="UTC")
            df = parse_records(text, (lo, hi))
            if len(df):
                got_any = True
                save_raw(SOURCE, f"{ds}_{day}.json", text.encode(), raw_dir)
                frames.append(df.assign(_kind=kind))
            day += timedelta(days=1)
            polite_sleep(pause_s)
        if not got_any:
            log.info("RTE: dataset %s contributed nothing for %s..%s", ds, start, end)
    if not frames:
        raise IngestError(f"RTE: nothing downloaded for {start}..{end}")
    # cons-def (historic) wins over rolling on overlaps; non-null wins over null
    merged = (
        pd.concat(frames, ignore_index=True)
        .sort_values(
            ["timestamp", "_kind"],
            key=lambda s: s.map({"historic": 0, "rolling": 1}) if s.name == "_kind" else s,
        )
        .drop_duplicates(subset="timestamp", keep="first")
        .drop(columns="_kind")
    )
    return normalize(merged, MARKET, REGION, SOURCE)
