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


def _daily_temps(unit: str, start: date, end: date) -> pd.Series:
    w = unit_weather(unit, start, end)
    return w.groupby(w.index.tz_convert(UNIT_TZ[unit]).date)["w_temperature_2m"].mean()


def _cold_dates_with_provenance(
    frame: pd.DataFrame, unit: str
) -> tuple[set[date], dict]:
    """Cold-decile days of the EVALUATION window, with the threshold learned
    ONLY on the pre-evaluation reference period (train-only stance; avoids the
    soft leakage of selecting slices from the window being measured).

    Reference: the 90 days immediately before the first evaluated timestamp.
    Fallback (reference < 20 days): whole-window decile, flagged honestly.
    """
    eval_start = frame["timestamp"].min().date()
    eval_end = frame["timestamp"].max().date()
    tz = UNIT_TZ[unit]
    ref_start = eval_start - pd.Timedelta(days=90)
    ref_end = eval_start - pd.Timedelta(days=1)
    eval_daily = _daily_temps(unit, eval_start, eval_end)
    ref_daily = _daily_temps(unit, ref_start, ref_end)
    if len(ref_daily) >= 20:
        threshold = float(ref_daily.quantile(COLD_DECILE))
        basis = f"pre-evaluation reference ({len(ref_daily)} days)"
    else:
        threshold = float(eval_daily.quantile(COLD_DECILE))
        basis = f"whole-window (insufficient reference: {len(ref_daily)} days)"
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
