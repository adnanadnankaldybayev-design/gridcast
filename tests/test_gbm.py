"""GBM integration: on a synthetic temperature-driven demand series the
weather-aware GBM must beat the seasonal-naive baseline. Fully offline:
weather is injected via weather.seed_point_data."""

import numpy as np
import pandas as pd
import pytest

from gridcast.features.weather import POINTS, seed_point_data
from gridcast.models.gbm import GBMModel
from gridcast.models.naive import SeasonalNaive

STEP_MIN = 30
STEPS_PER_DAY = 48
WEEK_STEPS = 7 * STEPS_PER_DAY


def synth_weather(days=40, start="2026-02-01"):
    """Hourly synthetic weather: seasonal + daily temperature wave, wind, humidity."""
    idx = pd.date_range(start, periods=days * 24, freq="h", tz="UTC")
    h = idx.hour.to_numpy()
    d = np.arange(len(idx)) / 24.0
    temp = 6.0 + 4.0 * np.sin(2 * np.pi * d / 30) + 3.0 * np.sin(2 * np.pi * h / 24)
    return pd.DataFrame(
        {
            "temperature_2m": temp.astype("float32"),
            "relative_humidity_2m": (70 + 10 * np.sin(2 * np.pi * h / 24)).astype("float32"),
            "wind_speed_10m": (12 + 4 * np.sin(2 * np.pi * d / 12)).astype("float32"),
        },
        index=idx,
    )


def synth_demand(weather_hourly, days=40, start="2026-02-01"):
    """30-min demand with weekly shape + heating response to the same weather."""
    idx = pd.date_range(start, periods=days * STEPS_PER_DAY, freq="30min", tz="UTC")
    s = (idx - idx[0]).total_seconds().to_numpy()
    week = 7 * 86400
    base = 18000 + 4000 * np.sin(2 * np.pi * (s % week) / week)
    temp = np.interp(
        s,
        (weather_hourly.index - weather_hourly.index[0]).total_seconds(),
        weather_hourly["temperature_2m"],
    )
    hdd18 = np.clip(18 - temp, 0, None)
    return pd.Series(base + 900 * hdd18, index=idx, name="demand_mw")


@pytest.fixture
def seeded_gb_weather():
    w = synth_weather()
    for lat, lon, _w in POINTS["GB"]:
        seed_point_data(lat, lon, w)
    return w


def test_gbm_weather_beats_naive_on_temperature_driven_demand(seeded_gb_weather):
    demand = synth_demand(seeded_gb_weather)
    cut = demand.index[30 * STEPS_PER_DAY]  # 30 days history, last 10 days for eval
    history = demand.loc[:cut]
    horizon = pd.date_range(
        cut + pd.Timedelta(minutes=STEP_MIN), periods=2 * STEPS_PER_DAY, freq="30min"
    )
    actual = demand.loc[horizon]

    gbm = GBMModel("GB", "GB", use_weather=True)
    gbm.fit(history)
    gbm_mae = (gbm.predict(horizon) - actual).abs().mean()

    naive = SeasonalNaive()
    naive.fit(history)
    naive_mae = (naive.predict(horizon) - actual).abs().mean()

    assert gbm_mae < naive_mae
    # temperature-driven part is ~900*HDD ~ several GW; weather-blind naive misses it
    assert gbm_mae < 3500


def test_gbm_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="predict before fit"):
        GBMModel("GB", "GB", use_weather=False).predict(
            pd.date_range("2026-03-01", periods=4, freq="h", tz="UTC")
        )


def test_gbm_too_little_history_raises():
    s = pd.Series(1.0, index=pd.date_range("2026-03-01", periods=50, freq="h", tz="UTC"))
    with pytest.raises(ValueError, match="too little history"):
        GBMModel("GB", "GB", use_weather=False).fit(s)
