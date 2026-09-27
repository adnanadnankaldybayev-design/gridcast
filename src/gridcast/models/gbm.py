"""LightGBM point-forecast model — same fit/predict protocol as SeasonalNaive.

Multistep strategy: DIRECT, one global model per (market, unit). For each
horizon timestamp we build features that depend only on data published at the
issue cutoff (calendar, concurrent weather, season-safe lags read from the
cut history). No recursion: predictions never feed other predictions, so
errors cannot compound; late-horizon availability gaps show up as NaN lags,
which LightGBM routes natively.

Documented limitation: train rows always have full lags available (historical
actuals), far-horizon predict rows may see lag_24h/lag_48h as NaN — a small
distribution shift we accept for simplicity; the seasonal lags (168h/336h)
are always published and dominate by design.

Hyperparameters are FIXED here (no tuning on the backtest window). The only
stopping rule uses the last VALID_DAYS days of the fit window — strictly
inside the anchor's history, so the protocol stays leak-free.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import lightgbm as lgb
import pandas as pd

from gridcast.features.build import build_features
from gridcast.features.weather import unit_weather

log = logging.getLogger(__name__)

LGB_PARAMS = {
    "objective": "regression",
    "n_estimators": 2000,  # capped by early stopping
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 20,
    "subsample": 0.9,
    "subsample_freq": 1,
    "colsample_bytree": 0.9,
    "reg_lambda": 1.0,
    "n_jobs": -1,
    "verbose": -1,
    # reproducible boosting (bagging subsample uses a fixed seed);
    # the leak-guard test depends on bit-identical refits
    "random_state": 42,
    "deterministic": True,   # ordered histograms — identica to next run
}
EARLY_STOP_ROUNDS = 50
VALID_DAYS = 14  # tail of the fit window used only for early stopping


@dataclass
class GBMModel:
    market: str
    unit: str
    use_weather: bool = True
    # 24h/48h lags: NOT publication-safe for a 48h direct forecast (GB: never
    # published; see features/build.py). Keep off until a recursive strategy.
    short_lags: bool = False
    params: dict = field(default_factory=lambda: dict(LGB_PARAMS))

    def __post_init__(self):
        self.name = f"lightgbm-{'weather' if self.use_weather else 'no-weather'}"
        self._reg = None
        self._history = None
        self._feature_cols = None

    def _weather_for(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
        if not self.use_weather:
            return None
        return unit_weather(self.unit, start.date(), end.date())

    def _predict_weather(self, weather: pd.DataFrame | None, timestamps: pd.DatetimeIndex):
        """Weather for a predict window: explicit frame (e.g. NWP forecast for
        future horizons in the daily runner) wins; archive via unit_weather otherwise."""
        if weather is not None or not self.use_weather:
            return weather
        return self._weather_for(timestamps[0], timestamps[-1])

    def update_history(self, history: pd.Series) -> None:
        """Periodic-refit mode: swap the lag lookup window, keep the fitted trees."""
        self._history = history.dropna()

    def fit(self, history: pd.Series) -> None:
        hist = history.dropna()
        if len(hist) < 200:
            raise ValueError(f"GBMModel {self.unit}: too little history ({len(hist)})")
        self._history = hist
        weather = self._weather_for(hist.index[0], hist.index[-1])  # concurrent only
        X = build_features(
            hist.index,
            self.market,
            self.unit,
            hist,
            weather,
            use_weather=self.use_weather,
            include_short_lags=self.short_lags,
        )
        y = hist.astype("float32")
        split = y.index[-1] - pd.Timedelta(days=VALID_DAYS)
        reg = lgb.LGBMRegressor(**self.params)
        reg.fit(
            X[X.index <= split],
            y[y.index <= split],
            eval_X=X[X.index > split],
            eval_y=y[y.index > split],
            callbacks=[lgb.early_stopping(EARLY_STOP_ROUNDS, verbose=False)],
        )
        self._reg = reg
        self._feature_cols = list(X.columns)
        log.info(
            "GBM %s/%s: trained %s iters on %d rows",
            self.market,
            self.unit,
            reg.best_iteration_,
            int((X.index <= split).sum()),
        )

    def predict(
        self, timestamps: pd.DatetimeIndex, weather: pd.DataFrame | None = None
    ) -> pd.Series:
        if self._reg is None:
            raise RuntimeError("GBMModel: predict before fit")
        w = self._predict_weather(weather, timestamps)
        X = build_features(
            timestamps,
            self.market,
            self.unit,
            self._history,
            w,
            use_weather=self.use_weather,
            include_short_lags=self.short_lags,
        )
        preds = self._reg.predict(X[self._feature_cols])
        return pd.Series(preds, index=timestamps, name="prediction")
