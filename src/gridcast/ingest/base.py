"""Shared plumbing for ingest adapters: HTTP with retries, raw snapshots,
month/week calendars, the normalized demand schema and Parquet output."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from gridcast.config import CADENCE_MINUTES, PROCESSED_DIR, RAW_DIR

log = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["timestamp", "market", "region", "demand_mw", "forecast_mw", "source"]


class IngestError(RuntimeError):
    """Fatal error for one adapter run (network exhausted, unexpected payload...)."""


def make_session() -> requests.Session:
    retry = Retry(
        total=6,
        backoff_factor=2.0,  # 2s, 4s, 8s, ...
        # 403 too: ODS/RTE answers 403 under rate pressure with Retry-After
        status_forcelist=(403, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "gridcast/0.1 (open research; github: gridcast)"})
    return session


def fetch(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 120,
) -> bytes:
    try:
        resp = session.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        # adapters and the CLI only handle IngestError
        raise IngestError(f"GET {url} failed: {exc}") from exc
    if resp.status_code != 200:
        raise IngestError(f"GET {resp.url} -> HTTP {resp.status_code}")
    return resp.content


def save_raw(source: str, name: str, content: bytes, raw_dir: Path | None = None) -> Path:
    """Keep the untouched upstream response; operators change formats without notice."""
    raw_dir = raw_dir or RAW_DIR
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / source / f"{stamp}_{name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def month_range(start: date, end: date) -> list[str]:
    """Inclusive list of 'YYYY-MM' labels covering [start, end]."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def week_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """Consecutive 7-day windows covering [start, end] (clipped at `end`)."""
    out = []
    cur = start
    step = pd.Timedelta(days=6)
    one_day = pd.Timedelta(days=1)
    while cur <= end:
        fin = min(cur + step, end)
        out.append((cur, fin))
        cur = fin + one_day
    return out


def midnight_utc(local_dates: pd.Series, tz: str) -> pd.Series:
    """UTC instant of local midnight for each date — DST-safe anchor."""
    midnights = pd.to_datetime(local_dates).dt.tz_localize(tz)
    return midnights.dt.tz_convert("UTC")


def normalize(df: pd.DataFrame, market: str, region: str, source: str) -> pd.DataFrame:
    """Project adapter output onto the canonical schema and validate it."""
    out = df.copy()
    out["market"] = market
    out["region"] = region
    out["source"] = source
    out = (
        out[["timestamp", "market", "region", "demand_mw", "forecast_mw", "source"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if out.empty:
        raise IngestError(f"{market}/{region}: adapter produced no rows")
    if str(out["timestamp"].dtype) != "datetime64[us, UTC]":
        out["timestamp"] = out["timestamp"].dt.tz_convert("UTC").astype("datetime64[us, UTC]")
    out["demand_mw"] = pd.to_numeric(out["demand_mw"], errors="coerce").astype("float64")
    out["forecast_mw"] = pd.to_numeric(out["forecast_mw"], errors="coerce").astype("float64")
    if out.duplicated(subset=["timestamp", "region"]).any():
        raise IngestError(f"{market}/{region}: duplicate (timestamp, region) after normalization")
    demand = out["demand_mw"].dropna()
    if demand.empty:
        raise IngestError(f"{market}/{region}: no actual demand values")
    if (demand.abs() > 1_000_000).any():
        raise IngestError(f"{market}/{region}: absurd demand magnitude (unit bug?)")
    negatives = int((demand < 0).sum())
    if negatives:
        # real in high-solar regions (e.g. SA1 operational demand dips below 0 MW)
        log.warning(
            "%s/%s: %d negative demand intervals (real DER effect), kept",
            market,
            region,
            negatives,
        )
    return out[SCHEMA_COLUMNS]


def write_parquet(df: pd.DataFrame, market: str, out_dir: Path | None = None) -> list[Path]:
    """Write monthly partition files demand_{MARKET}_{YYYY-MM}.parquet.

    Months present in `df` are merged with any existing partition on disk
    (fresh rows win on (timestamp, region) conflicts), so a narrow incremental
    re-ingest never truncates earlier history. Writes go through a temp file +
    os.replace, so an interrupted run cannot leave a half-written partition
    behind."""
    out_dir = out_dir or PROCESSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for ym, part in df.groupby(df["timestamp"].dt.strftime("%Y-%m")):
        path = out_dir / f"demand_{market}_{ym}.parquet"
        if path.exists():
            part = (
                pd.concat([pd.read_parquet(path), part], ignore_index=True)
                .drop_duplicates(subset=["timestamp", "region"], keep="last")
                .sort_values("timestamp")
            )
        tmp = path.with_suffix(".tmp")
        try:
            part.reset_index(drop=True).to_parquet(tmp, index=False)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        written.append(path)
    return written


def read_processed(market: str, out_dir: Path | None = None) -> pd.DataFrame:
    out_dir = out_dir or PROCESSED_DIR
    files = sorted(out_dir.glob(f"demand_{market}_*.parquet"))
    if not files:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def summarize(df: pd.DataFrame, market: str) -> dict:
    """Coverage stats for the ingest report (rows, span, % of expected grid missing).
    Coverage is measured on rows with an actual demand value, per region."""
    step_min = CADENCE_MINUTES[market]
    actual_rows = df.dropna(subset=["demand_mw"])
    ts = actual_rows["timestamp"].sort_values()
    regions = {}
    for region, part in actual_rows.groupby("region"):
        rts = part["timestamp"].sort_values()
        expected = int((rts.iloc[-1] - rts.iloc[0]).total_seconds() // (60 * step_min)) + 1
        regions[region] = {
            "rows": len(part),
            "first": str(rts.iloc[0]),
            "last": str(rts.iloc[-1]),
            "missing_pct": round(100.0 * (1 - rts.nunique() / expected), 3),
        }
    return {
        "market": market,
        "rows": len(df),
        "first": str(ts.iloc[0]),
        "last": str(ts.iloc[-1]),
        "regions": regions,
    }


def polite_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
