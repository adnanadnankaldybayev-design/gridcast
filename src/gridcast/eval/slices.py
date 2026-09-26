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
from gridcast.ingest.base import IngestError

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


def _daily_temps(unit: str, start: date, end: date) -> pd.Series:
    w = unit_weather(unit, start, end)
    return w.groupby(w.index.tz_convert(UNIT_TZ[unit]).date)["w_temperature_2m"].mean()


def _cold_dates_with_provenance(
    frame: pd.DataFrame, unit: str
) -> tuple[set[date], dict]:
    """Cold-decile days of the EVALUATION window against CLIMATOLOGY: the
    threshold is the 10th percentile of last year's daily means over the same
    calendar months (never the measured window itself). Reference year is
    fetched from the same Open-Meteo archive; fallback to whole-window decile
    is flagged honestly if history is unavailable.
    """
    eval_start = frame["timestamp"].min().date()
    eval_end = frame["timestamp"].max().date()
    tz = UNIT_TZ[unit]
    eval_daily = _daily_temps(unit, eval_start, eval_end)
    # climatology: same months one year back
    ref_start = date(eval_start.year - 1, eval_start.month, eval_start.day)
    ref_end = date(eval_end.year - 1, eval_end.month, min(eval_end.day, 28))
    basis = None
    try:
        ref_daily = _daily_temps(unit, ref_start, ref_end)
        min_days = max(7, int(0.9 * (eval_end - eval_start).days))
        if len(ref_daily) >= min_days:
            threshold = float(ref_daily.quantile(COLD_DECILE))
            basis = f"climatology {ref_start.year} same months ({len(ref_daily)} days)"
    except IngestError:
        basis = None
    if basis is None:
        threshold = float(eval_daily.quantile(COLD_DECILE))
        basis = "whole-window (climatology unavailable)"
    return set(eval_daily[eval_daily <= threshold].index), {
        "threshold_c": round(threshold, 2),
        "threshold_basis": basis,
        "tz": tz,
    }


def slice_metrics(
    unit_frames: dict[str, pd.DataFrame], unit: str, floor_mw: float = 100.0
) -> dict:
    """unit_frames: model -> frame. Returns {slice: {model: metrics}} plus
    slice sizes, threshold provenance and the cold-day list for transparency."""
    if not unit_frames:
        return {}
    any_frame = next(iter(unit_frames.values()))
    day_slices = _slice_dates(any_frame, unit)
    cold_dates, cold_meta = _cold_dates_with_provenance(any_frame, unit)
    day_slices["cold_10pct"] = cold_dates

    out = {}
    for name, dates in day_slices.items():
        out[name] = {"n_days": len(dates)}
        for model, frame in unit_frames.items():
            mask = _local_dates(frame["timestamp"], unit).isin(dates)
            sub = frame[mask]
            out[name][model] = (
                summarize(sub["actual"], sub["predicted"], floor_mw) if len(sub) else None
            )
    out["cold_10pct"]["dates"] = sorted(str(d) for d in day_slices["cold_10pct"])
    out["cold_10pct"].update(cold_meta)
    return out
