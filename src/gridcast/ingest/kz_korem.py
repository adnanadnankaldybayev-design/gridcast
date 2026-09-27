"""Kazakhstan — KOREM clearing trade demand (portal.korem.kz), no key.

Verified live 2026-09-27:
  GET https://portal.korem.kz/api/ct/series?zoneId={z}&torgNameId=4&from=YYYY-MM-DD&to=YY...
  -> [{"dt":"2026-09-01T00:00:00","demand":2161.379,"supply":...,"deal":...}, ...]
  Hourly. Zones: 1 "Север - Юг" -> unit KZ, 2 "Запад" -> unit KZ_W. History
  from 2023-07-01, full coverage (verified 8784/8784h in 2024), single request
  per zone per full range suffices, no auth.

  HONESTY (pinned in README): `demand` here is the *clearing* (centralized-
  trade) demand, ~25-45% of physical consumption — NOT physical grid load.
  /api/energy/series gives daily physical gen/cons (GWh) as a cross-check.
  That is the series we forecast: the same documented definition per timestamp.

  TIMEZONE (trap pinned by tests): dt labels are naive civil time; the legal
  offset changed 2024-03-01 from UTC+6 to UTC+5 (Asia/Almaty). Labels map
  piecewise: < 2024-03-01 -> +06:00, >= -> +05:00.
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

API = "https://portal.korem.kz/api/ct/series"
ZONES = {1: "KZ", 2: "KZ_W"}
MARKET = "KZ"
SOURCE = "korem"
TZ_SWITCH_LOCAL = pd.Timestamp("2024-03-01 00:00")  # UTC+6 before, UTC+5 after


def parse_series(payload: str) -> pd.DataFrame:
    records = json.loads(payload)
    if not isinstance(records, list):
        raise IngestError(f"KOREM: unexpected payload type {type(records)}: {payload[:200]}")
    rows = []
    for rec in records:
        dt = rec.get("dt")
        if dt is None:
            raise IngestError(f"KOREM: record without dt: {sorted(rec)[:8]}")
        naive = pd.Timestamp(dt)
        offset_h = 6 if naive < TZ_SWITCH_LOCAL else 5
        ts_utc = (naive - pd.Timedelta(hours=offset_h)).tz_localize("UTC")
        demand = rec.get("demand")
        rows.append(
            (
                ts_utc,
                float(demand) if demand is not None else None,
                None,
            )
        )
    out = pd.DataFrame(rows, columns=["timestamp", "demand_mw", "forecast_mw"])
    return out[out["demand_mw"].notna()].sort_values("timestamp").reset_index(drop=True)


def ingest(start: date, end: date, *, raw_dir=None, session=None, pause_s: float = 1.0):
    session = session or make_session()
    frames = []
    for zone_id, region in ZONES.items():
        log.info("KOREM: zone %s (%s)", zone_id, region)
        text = fetch(
            session,
            API,
            params={
                "zoneId": zone_id,
                "torgNameId": 4,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
            timeout=300,
        ).decode("utf-8")
        save_raw(SOURCE, f"ct_series_zone{zone_id}_{start}_{end}.json", text.encode(), raw_dir)
        df = parse_series(text)
        lo = pd.Timestamp(start, tz="UTC")
        hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        df = df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)]
        frames.append(df.assign(_region=region))
        polite_sleep(pause_s)
    if not frames:
        raise IngestError(f"KOREM: nothing downloaded for {start}..{end}")
    normalized = []
    for region, part in pd.concat(frames, ignore_index=True).groupby("_region"):
        normalized.append(normalize(part.drop(columns="_region"), MARKET, region, SOURCE))
    return pd.concat(normalized, ignore_index=True)
