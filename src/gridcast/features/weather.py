"""Weather features from the Open-Meteo Archive API (free, no key).

Verified live 2026-09-26: https://archive-api.open-meteo.com/v1/archive,
hourly temperature_2m / relative_humidity_2m / wind_speed_10m, timezone=UTC,
data available up to ~T-1 day.

Pragmatic point choice (documented, population/demand weighted) — all config,
new markets are one row each in POINTS:
  GB         London 0.45, Manchester 0.35, Glasgow 0.20
  IE (All-Island) Dublin 1.0 (island demand & population concentrate on ROI)
  AU regions one capital per NEM region:
  NSW1 Sydney, QLD1 Brisbane, VIC1 Melbourne, SA1 Adelaide, TAS1 Hobart
  NEM_TOTAL  consumption-share composite NSW .40, QLD .25, VIC .25, SA .08, TAS .02

HONESTY (limitation): in backtests this is *archived reanalysis* — a proxy
for a perfect weather forecast. Live day-ahead operation will use the NWP
forecast instead; the weather ablation (gbm vs gbm-no-weather) bounds the
benefit a real weather forecast can add.

Caching: one append-only parquet per weather point
(data/raw/weather/{lat}_{lon}.parquet, gitignored), merged atomically after
every fetch — no thousand-file snapshot litter. Legacy per-request JSON
snapshots are still READ (backward compatibility) and collapsed into the
parquet store by migrate_weather_cache(); per-point memo in-process grows to
cover every requested range, so a full backtest is network-free after warmup.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from gridcast.config import RAW_DIR
from gridcast.ingest.base import IngestError, fetch, make_session

log = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"  # NWP forecast, no key
VARIABLES = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m")

POINTS: dict[str, tuple[tuple[float, float, float], ...]] = {
    "GB": ((51.5074, -0.1278, 0.45), (53.4808, -2.2426, 0.35), (55.8642, -4.2518, 0.20)),
    "ALL": ((53.3498, -6.2603, 1.0),),
    "NSW1": ((-33.8688, 151.2093, 1.0),),
    "QLD1": ((-27.4698, 153.0251, 1.0),),
    "SA1": ((-34.9285, 138.6007, 1.0),),
    "TAS1": ((-42.8821, 147.3272, 1.0),),
    "VIC1": ((-37.8136, 144.9631, 1.0),),
    "NEM_TOTAL": (
        (-33.8688, 151.2093, 0.40),
        (-27.4698, 153.0251, 0.25),
        (-37.8136, 144.9631, 0.25),
        (-34.9285, 138.6007, 0.08),
        (-42.8821, 147.3272, 0.02),
    ),
    "FR": (
        (48.8566, 2.3522, 0.60),  # Paris
        (45.7640, 4.8357, 0.20),  # Lyon
        (43.2965, 5.3698, 0.20),  # Marseille
    ),
    "DE": (
        (52.5200, 13.4050, 0.30),  # Berlin
        (50.9375, 6.9603, 0.30),  # Cologne (NRW, demand-heavy)
        (48.1351, 11.5820, 0.25),  # Munich
        (53.5511, 9.9937, 0.15),  # Hamburg
    ),
    "BE": (
        (50.8503, 4.3517, 0.60),  # Brussels
        (51.2194, 4.4025, 0.40),  # Antwerp (petrochemical load)
    ),
    "DK": (
        (55.6761, 12.5683, 0.60),  # Copenhagen
        (56.1629, 10.2039, 0.40),  # Aarhus
    ),
    "KZ": ((43.2400, 76.8900, 1.0),),  # Almaty / Almaty (proxy both zones)
    "KZ_W": ((43.2400, 76.8900, 1.0),),
}

WEATHER_CACHE_DIR = RAW_DIR / "weather"

_point_memo: dict[tuple[float, float], pd.DataFrame] = {}


def parse_response(text: str) -> pd.DataFrame:
    payload = json.loads(text)
    hourly = payload.get("hourly")
    if not hourly or "time" not in hourly:
        raise IngestError(f"Open-Meteo: unexpected payload keys {sorted(payload)}")
    df = pd.DataFrame(hourly)
    ts = pd.to_datetime(df.pop("time"))
    # real API sends naive strings; tolerate tz-aware too (tests, future formats)
    df["timestamp"] = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts.dt.tz_convert("UTC")
    df = df.set_index("timestamp").sort_index()
    missing = [v for v in VARIABLES if v not in df.columns]
    if missing:
        raise IngestError(f"Open-Meteo: missing variables {missing}")
    return df.astype("float32")


def _point_parquet(cache_dir: Path, lat: float, lon: float) -> Path:
    return cache_dir / f"{lat:.4f}_{lon:.4f}.parquet"


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    import os

    tmp = path.with_suffix(".tmp")
    try:
        df.reset_index().to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _merge(a: pd.DataFrame | None, b: pd.DataFrame) -> pd.DataFrame:
    if a is None:
        return b.sort_index()
    out = pd.concat([a, b])
    return out[~out.index.duplicated(keep="last")].sort_index()


def _download_range(session, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    content = fetch(
        session,
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(VARIABLES),
            "timezone": "UTC",
        },
        timeout=120,
    )
    df = parse_response(content.decode("utf-8"))
    cache_dir = WEATHER_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _point_parquet(cache_dir, lat, lon)
    have = pd.read_parquet(path).set_index("timestamp") if path.exists() else None
    _atomic_write_parquet(_merge(have, df), path)
    return df


def _seed_from_disk(key: tuple[float, float], cache_dir: Path) -> pd.DataFrame | None:
    """Load the per-point parquet plus any legacy JSON snapshots (backward
    compatibility), merged and deduplicated. Network-free after warmup."""
    lat, lon = key
    have = None
    pq = _point_parquet(cache_dir, lat, lon)
    if pq.exists():
        have = pd.read_parquet(pq).set_index("timestamp").sort_index()
    frames = []
    for path in cache_dir.glob(f"*_{lat:.4f}_{lon:.4f}_*.json"):
        try:
            frames.append(parse_response(path.read_text(encoding="utf-8")))
        except IngestError:
            log.warning("Open-Meteo: unparsable snapshot skipped: %s", path.name)
    for f in frames:
        have = _merge(have, f)
    return have


def migrate_weather_cache(cache_dir: Path | None = None) -> dict:
    """One-time migration: collapse legacy per-request JSON snapshots into the
    per-point parquet store, then delete the legacy files. Safe to re-run."""
    cache_dir = cache_dir or WEATHER_CACHE_DIR
    migrated = {}
    legacy = sorted(p for p in cache_dir.glob("*.json") if p.name.count("_") >= 4)
    points = {}
    for path in legacy:
        parts = path.stem.split("_")
        try:
            lat, lon = float(parts[1]), float(parts[2])
        except (ValueError, IndexError):
            log.warning("migrate: cannot parse point from %s, skipped", path.name)
            continue
        points.setdefault((lat, lon), []).append(path)
    for (lat, lon), paths in points.items():
        have = None
        pq = _point_parquet(cache_dir, lat, lon)
        if pq.exists():
            have = pd.read_parquet(pq).set_index("timestamp")
        for path in paths:
            try:
                have = _merge(have, parse_response(path.read_text(encoding="utf-8")))
            except IngestError:
                log.warning("migrate: unparsable %s, skipped", path.name)
                continue
            path.unlink()
        if have is not None and len(have):
            have = have.sort_index()
            _atomic_write_parquet(have, pq)
            migrated[f"{lat:.4f}_{lon:.4f}"] = len(have)
    log.info("migrate_weather_cache: %s", migrated)
    return migrated


def point_data(
    lat: float, lon: float, start: date, end: date, session=None
) -> pd.DataFrame:
    """Hourly weather for one point over [start, end]; per-point memo grows to
    cover any requested span (one fetch per uncovered extension)."""
    key = (round(lat, 4), round(lon, 4))
    have = _point_memo.get(key)
    if have is None:
        have = _seed_from_disk(key, WEATHER_CACHE_DIR)
    if have is not None and len(have):
        have = have[~have.index.duplicated(keep="last")].sort_index()
        _point_memo[key] = have
    have_min = have.index[0].date() if have is not None and len(have) else None
    have_max = have.index[-1].date() if have is not None and len(have) else None
    if have is None or start < have_min or end > have_max:
        session = session or make_session()
        fetch_start = min(start, have_min) if have_min else start
        fetch_end = max(end, have_max) if have_max else end
        fresh = _download_range(session, lat, lon, fetch_start, fetch_end)
        have = pd.concat([have, fresh]) if have is not None else fresh
        have = have[~have.index.duplicated(keep="last")].sort_index()
        _point_memo[key] = have
        log.info("Open-Meteo: %s now covers %s..%s (%d h)", key, have_min, have_max, len(have))
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return have.loc[(have.index >= start_ts) & (have.index < end_ts)]


def seed_point_data(lat: float, lon: float, df: pd.DataFrame) -> None:
    """Inject stored weather (tests / offline runs)."""
    _point_memo[(round(lat, 4), round(lon, 4))] = df.sort_index()


def unit_weather(
    unit: str, start: date, end: date, session=None
) -> pd.DataFrame:
    """Weighted-mean hourly weather for a market unit, UTC index."""
    parts = []
    for lat, lon, weight in POINTS[unit]:
        parts.append(point_data(lat, lon, start, end, session) * weight)
    out = parts[0]
    for p in parts[1:]:
        out = out.add(p, fill_value=None)
    out.columns = [f"w_{c}" for c in out.columns]
    return out.sort_index()


def unit_weather_forecast(unit: str, hours_ahead: int, session=None) -> pd.DataFrame:
    """NWP forecast (hourly) for the next `hours_ahead` hours, weighted per
    market point config — the honest future counterpart of the archive."""
    from datetime import datetime

    session = session or make_session()
    frames = []
    for lat, lon, weight in POINTS[unit]:
        content = fetch(
            session,
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": ",".join(VARIABLES),
                "timezone": "UTC",
                "forecast_days": (hours_ahead + 23) // 24 + 1,
            },
            timeout=120,
        )
        frames.append(parse_response(content.decode("utf-8")) * weight)
    out = frames[0]
    for f in frames[1:]:
        out = out.add(f, fill_value=None)
    out.columns = [f"w_{c}" for c in out.columns]
    now = pd.Timestamp(datetime.now(), tz="UTC").floor("h")
    return out[out.index >= now].sort_index()
