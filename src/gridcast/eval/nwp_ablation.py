"""Archive-weather advantage measured honestly: GBM trained/verified on
reanalysis (= perfect-forecast proxy) vs the same GBM fed a noise-degraded
version of that weather.

Assumption (documented): 24-48h NWP temperature-2m error ~ N(0, 1.75 C)
(working-level day-ahead scale; quoted as a modeling choice, not a universal
constant). Multiplicative degradation is NOT applied: cold-snap tails would
shrink illogically - additive Gaussian noise is the conservative, simple,
documented choice here.

Only w_temperature_2m is perturbed; humidity/wind stay; HDD/CDD are derived
in build.py, so the cooling/heating signals degrade honestly too.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from gridcast.eval.backtest import BacktestConfig, run_backtest
from gridcast.features import weather as _weather_module

DEFAULT_SIGMA_C = 1.75


def _noisy_weather(unit: str, start, end, sigma: float, seed_tag: str):
    """unit_weather with the temperature column perturbed by deterministic noise."""
    base = _weather_module.unit_weather(
        unit, start.date() if hasattr(start, "date") else start,
        end.date() if hasattr(end, "date") else end,
    )
    key = hashlib.sha256(f"{unit}:{start}:{end}:{seed_tag}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(key[:4], "little"))
    noise = pd.Series(rng.normal(0.0, sigma, size=len(base)), index=base.index)
    noised = base.copy()
    noised["w_temperature_2m"] = base["w_temperature_2m"] + noise
    return noised


def _make_noisy_weather(unit: str, start, end, sigma: float):
    """Closure producing ONE deterministic noisy weather frame per experiment
    (cached — the same frame feeds every fit and predict for stable traces)."""
    base = _weather_module.unit_weather(
        unit, start.date() if hasattr(start, "date") else start,
        end.date() if hasattr(end, "date") else end,
    )
    key = hashlib.sha256(f"{unit}:{start}:{end}:{sigma}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(key[:4], "little"))
    noised = base.copy()
    noised["w_temperature_2m"] = base["w_temperature_2m"] + pd.Series(
        rng.normal(0.0, sigma, size=len(base)), index=base.index
    )

    def provider(u, s, e, session=None):
        return noised

    return provider


def run_nwp_ablation(
    markets_units: list[tuple[str, str]],
    start: pd.Timestamp,
    end: pd.Timestamp,
    sigma: float = DEFAULT_SIGMA_C,
    data_dir=None,
) -> dict:
    """Compare identical GBM configs on reanalysis vs noise-degraded weather.

    The weather source is swapped through gridcast.models.gbm.unit_weather,
    which is the binding GBM/Ridge actually resolve at fit/predict time.
    """
    import gridcast.models.gbm as gbm_mod

    original_unit_weather = gbm_mod.unit_weather
    results = {}
    try:
        for market, unit in markets_units:
            frames = {}
            for tag in ("archive", "noisy"):
                if tag == "noisy":
                    gbm_mod.unit_weather = _make_noisy_weather(unit, start, end, sigma)
                else:
                    gbm_mod.unit_weather = original_unit_weather
                cfg = BacktestConfig(model="lightgbm-weather", refit_every_anchors=7)
                report, frame_map = run_backtest((market,), start, end, cfg, data_dir)
                frames[tag] = (report, frame_map[f"{market}/{unit}"])
            results[f"{market}/{unit}"] = frames
    finally:
        gbm_mod.unit_weather = original_unit_weather
    return results
