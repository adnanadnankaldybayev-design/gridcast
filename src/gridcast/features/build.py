"""Feature assembly: calendar + publication-safe demand lags (+ weather).

Lags are read from `history` by exact-timestamp lookup, so availability is
*derived from the cut history the engine hands the model*: a lag pointing past
the publication cutoff simply yields NaN (LightGBM handles NaN natively).
No feature for timestamp t ever reads a value recorded at t or later.
"""

from __future__ import annotations

import pandas as pd

from gridcast.features.calendar import calendar_frame

# Publication-safe lags differ per market, by the publication protocol's own
# math (proven by measurement and by spies):
#   t <= anchor+48h; source(t, lag) = t-lag must be <= cutoff = anchor-pub_lag.
#   IE/AU (lag 6h):   t-168h <= anchor-120h   <= anchor-6h    -> always safe
#   GB (lag 21d=504h): t-168h <= anchor-120h  >  anchor-504h   -> NEVER safe;
#                     lag must be >= 504h+48h; we use 672h (4w) and 840h (5w).
# Getting this wrong is silently catastrophic (verified 2026-09-26: with 168h
# lags the GB GBM predicted March levels in August, MAPE 24-25%).
MARKET_LAG_HOURS = {
    "GB": (672, 840),
    "IE": (168, 336),
    "AU": (168, 336),
    "FR": (168, 336),
    "DE": (168, 336),
    "BE": (168, 336),
    "DK": (168, 336),
    "KZ": (168, 336),
}
SHORT_LAG_HOURS = (24, 48)
# Short lags stay opt-in for future recursive strategies only.
WEATHER_COLS = ("w_temperature_2m", "w_relative_humidity_2m", "w_wind_speed_10m")
BASELINE_TEMP_C = 18.0


def lag_values(index: pd.DatetimeIndex, history: pd.Series, hours: int) -> pd.Series:
    """history[t-hours] for each t — exact-timestamp lookup inside `history`."""
    return history.reindex(index - pd.Timedelta(hours=hours))


def lag_features(
    index: pd.DatetimeIndex,
    history: pd.Series,
    lag_hours: tuple[int, ...],
    include_short_lags: bool = False,
) -> pd.DataFrame:
    """Demand lags for each t in `index`, looked up strictly inside `history`.

    `lag_hours` must already be publication-safe for the market (the model
    passes MARKET_LAG_HOURS[market]); include_short_lags opts into the
    recursion-only 24h/48h lags for EXPERIMENTS, never in the default pipeline.
    """
    main = min(lag_hours)  # main lag drives the weekly-level features
    lag_hours = tuple(lag_hours) + (SHORT_LAG_HOURS if include_short_lags else ())
    out = {}
    for hours in sorted(lag_hours):
        out[f"lag_{hours}h"] = lag_values(index, history, hours).to_numpy()
    rolled = history.rolling(pd.Timedelta(hours=24), min_periods=1).mean()
    out["r24_mean_lag_main"] = rolled.reindex(index - pd.Timedelta(hours=main)).to_numpy()
    out["lag_minus_weekly_mean"] = out[f"lag_{main}h"] - out["r24_mean_lag_main"]
    return pd.DataFrame(out, index=index)


def weather_features(index: pd.DatetimeIndex, weather: pd.DataFrame | None) -> pd.DataFrame:
    if weather is None:
        return pd.DataFrame(index=index)
    w = weather.reindex(index, method="ffill")  # hourly archive onto the grid
    temp = w["w_temperature_2m"]
    w["w_hdd18"] = (BASELINE_TEMP_C - temp).clip(lower=0)  # heating degree-hours
    w["w_cdd18"] = (temp - BASELINE_TEMP_C).clip(lower=0)  # cooling degree-hours
    return w


def build_features(
    index: pd.DatetimeIndex,
    market: str,
    unit: str,
    history: pd.Series,
    weather: pd.DataFrame | None = None,
    use_weather: bool = True,
    include_short_lags: bool = False,
) -> pd.DataFrame:
    parts = [
        calendar_frame(index, unit),
        lag_features(
            index,
            history,
            MARKET_LAG_HOURS[market],
            include_short_lags=include_short_lags,
        ),
    ]
    if use_weather:
        parts.append(weather_features(index, weather))
    return pd.concat(parts, axis=1).astype("float32")
