"""Day-type slice analysis (SPEC DoD #3): weekday / weekend / bank-holiday /
coldest-decile days, per unit and per model, computed from backtest frames.

`frames` maps unit -> model -> long-form backtest frame (anchor, timestamp,
actual, predicted, horizon_hours). Day membership uses each unit's local civil
date; cold days come from the unit's weighted weather (daily mean temperature,
bottom decile of the analysis window).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from gridcast.eval.metrics import summarize
from gridcast.features.calendar import UNIT_TZ, unit_holidays
from gridcast.features.weather import unit_weather

COLD_DECILE = 0.10


def _local_dates(ts: pd.Series, unit: str) -> pd.Series:
    return pd.Series(ts.dt.tz_convert(UNIT_TZ[unit]).dt.date, index=ts.index)


def _slice_dates(frame: pd.DataFrame, unit: str) -> dict[str, set[date]]:
    dates = _local_dates(frame["timestamp"], unit)
    years = range(min(dates).year, max(dates).year + 1)
    hols = unit_holidays(unit, years)
    weekday = set()
    weekend = set()
    for d in set(dates):
        (weekend if pd.Timestamp(d).dayofweek >= 5 else weekday).add(d)
    return {
        "weekday": weekday - hols,
        "weekend": weekend - hols,
        "bank_holiday": set(dates) & set(hols),
    }


def _cold_dates(frame: pd.DataFrame, unit: str) -> set[date]:
    start = frame["timestamp"].min().date()
    end = frame["timestamp"].max().date()
    w = unit_weather(unit, start, end)
    daily = w.groupby(w.index.tz_convert(UNIT_TZ[unit]).date)["w_temperature_2m"].mean()
    k = max(1, int(len(daily) * COLD_DECILE))
    return set(daily.nsmallest(k).index)


def slice_metrics(
    unit_frames: dict[str, pd.DataFrame], unit: str, floor_mw: float = 100.0
) -> dict:
    """unit_frames: model -> frame. Returns {slice: {model: metrics}} plus
    slice sizes and the cold-day list for transparency."""
    if not unit_frames:
        return {}
    any_frame = next(iter(unit_frames.values()))
    day_slices = _slice_dates(any_frame, unit)
    day_slices["cold_10pct"] = _cold_dates(any_frame, unit)

    out = {}
    for name, dates in day_slices.items():
        out[name] = {"n_days": len(dates)}
        for model, frame in unit_frames.items():
            mask = _local_dates(frame["timestamp"], unit).isin(dates)
            sub = frame[mask]
            out[name][model] = (
                summarize(sub["actual"], sub["predicted"], floor_mw) if len(sub) else None
            )
    if "cold_10pct" in day_slices:
        out["cold_10pct"]["dates"] = sorted(str(d) for d in day_slices["cold_10pct"])
    return out
