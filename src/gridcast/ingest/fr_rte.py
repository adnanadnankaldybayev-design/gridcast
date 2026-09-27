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

Fetching: ODRE's WAF rate-bans fast on per-day walks (measured: ~100 requests
in minutes → HTTP 400/403 openresty bans for tens of minutes). The records
API walk is replaced by the `/exports/csv` endpoint: ONE request per dataset
returns the whole filtered export as CSV (~10 MB). Day-walk fetch_day() and
parse_records() stay for contract tests only. Exports requests are spaced
>=20s apart.

Paging: server streams the full export; no pagination needed.
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


EXPORT_URL = "https://odre.opendatasoft.com/api/v2/catalog/datasets/{ds}/exports/csv"


def export_csv(
    session, ds: str, start: date, end: date, timeout: int = 900
) -> str:
    from gridcast.ingest.base import fetch

    return fetch(
        session,
        EXPORT_URL.format(ds=ds),
        params={
            "select": SELECT,
            "order_by": "date_heure",
            "where": (
                f"date_heure >= date'{start}' and "
                f"date_heure < date'{end + timedelta(days=1)}'"
            ),
        },
        timeout=timeout,
    ).decode("utf-8")


def parse_export_csv(text: str) -> pd.DataFrame:
    import io

    df = pd.read_csv(
        io.StringIO(text),
        sep=";",
        dtype={"consommation": "Float64", "prevision_j1": "Float64"},
    )
    need = {"date_heure", "consommation"}
    missing = need - set(df.columns)
    if missing:
        raise IngestError(f"RTE export: missing {sorted(missing)} (cols: {list(df.columns)[:10]})")
    ts = pd.to_datetime(df.pop("date_heure"), utc=False)
    ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")
    out = pd.DataFrame(
        {
            "timestamp": ts,
            "demand_mw": pd.to_numeric(df["consommation"], errors="coerce"),
            "forecast_mw": pd.to_numeric(df.get("prevision_j1"), errors="coerce"),
        }
    )
    return out.sort_values("timestamp").reset_index(drop=True)


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = PAUSE_S):
    session = session or make_session()
    frames = []
    for ds, kind in DATASETS:
        try:
            text = export_csv(session, ds, start, end)
        except IngestError:
            log.exception("RTE export %s failed", ds)
            polite_sleep(20)
            continue
        save_raw(SOURCE, f"{ds}_export_{start}_{end}.csv", text.encode(), raw_dir)
        df = parse_export_csv(text)
        lo = pd.Timestamp(start, tz="UTC")
        hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        df = df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)]
        if len(df):
            frames.append(df.assign(_kind=kind))
        polite_sleep(20)
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
