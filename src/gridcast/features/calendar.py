"""Calendar features per market unit.

Local civil time matters for demand (people live in local time), so calendar
features are computed from the unit's IANA timezone. Bank holidays come from
the `holidays` package: GB -> UnitedKingdom, IE -> Ireland, AU regions ->
Australia(subdiv=...). NEM_TOTAL uses Sydney (dominant demand centre).
"""

from __future__ import annotations

import holidays
import pandas as pd

UNIT_TZ = {
    "GB": "Europe/London",
    "ALL": "Europe/Dublin",
    "NSW1": "Australia/Sydney",
    "QLD1": "Australia/Brisbane",
    "SA1": "Australia/Adelaide",
    "TAS1": "Australia/Hobart",
    "VIC1": "Australia/Melbourne",
    "NEM_TOTAL": "Australia/Sydney",
    "FR": "Europe/Paris",
    "DE": "Europe/Berlin",
    "BE": "Europe/Brussels",
    "DK": "Europe/Copenhagen",
}

_HOLIDAY_SPEC = {
    # GB demand is dominated by England & Wales; 'GB' base misses Easter Monday
    "GB": ("GB", "ENG"),
    "ALL": ("IE", None),
    "NSW1": ("AU", "NSW"),
    "QLD1": ("AU", "QLD"),
    "SA1": ("AU", "SA"),
    "TAS1": ("AU", "TAS"),
    "VIC1": ("AU", "VIC"),
    "NEM_TOTAL": ("AU", "NSW"),
    "FR": ("FR", None),
    "DE": ("DE", None),
    "BE": ("BE", None),
    "DK": ("DK", None),
}

_cache: dict[str, set] = {}


def unit_holidays(unit: str, years) -> set:
    country, subdiv = _HOLIDAY_SPEC[unit]
    key = f"{country}:{subdiv}:{years.start}:{years.stop}"
    if key not in _cache:
        cal = holidays.country_holidays(country, subdiv=subdiv, years=list(years))
        _cache[key] = set(cal.keys())
    return _cache[key]


def calendar_frame(index: pd.DatetimeIndex, unit: str) -> pd.DataFrame:
    """Calendar features for UTC timestamps; index preserved (UTC)."""
    tz = UNIT_TZ[unit]
    local = index.tz_convert(tz)
    hols = unit_holidays(unit, range(local[0].year - 1, local[-1].year + 2))
    hour = local.hour + local.minute / 60.0
    dow = local.dayofweek
    return pd.DataFrame(
        {
            "hour_of_day": hour,
            "day_of_week": dow,
            "month": local.month,
            "is_weekend": (dow >= 5).astype(int),
            "is_holiday": [1 if d in hols else 0 for d in local.date],
            # morning and evening demand ramps (local civil time)
            "is_morning_ramp": ((hour >= 6) & (hour < 9)).astype(int),
            "is_evening_peak": ((hour >= 16) & (hour < 20)).astype(int),
        },
        index=index,
    )
