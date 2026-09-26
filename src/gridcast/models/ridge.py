"""Ridge regression on the same feature frame — the honest linear floor
between seasonal-naive and LightGBM. Same fit/predict/update_history protocol;
features are standardized (tree models don't need it, linear ones do).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from gridcast.features.build import build_features
from gridcast.features.weather import unit_weather

log = logging.getLogger(__name__)


@dataclass
class RidgeModel:
    market: str
    unit: str
    use_weather: bool = True
    alpha: float = 1.0

    def __post_init__(self):
        self.name = f"ridge-{'weather' if self.use_weather else 'no-weather'}"
        self._model = None
        self._history = None
        self._feature_cols = None

    def update_history(self, history: pd.Series) -> None:
        self._history = history.dropna()

    def _weather_for(self, start: pd.Timestamp, end: pd.Timestamp):
        if not self.use_weather:
            return None
        return unit_weather(self.unit, start.date(), end.date())

    def fit(self, history: pd.Series) -> None:
        hist = history.dropna()
        if len(hist) < 200:
            raise ValueError(f"RidgeModel {self.unit}: too little history ({len(hist)})")
        self._history = hist
        weather = self._weather_for(hist.index[0], hist.index[-1])
        X = build_features(
            hist.index, self.market, self.unit, hist, weather, use_weather=self.use_weather
        )
        y = hist.astype("float32")
        # lag warmup rows contain NaNs (no full season yet); median imputation
        # is the standard linear answer (trees route NaNs natively instead)
        self._model = make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=self.alpha)
        )
        self._model.fit(X, y)
        self._feature_cols = list(X.columns)
        log.info("Ridge %s/%s fitted on %d rows", self.market, self.unit, len(X))

    def predict(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        if self._model is None:
            raise RuntimeError("RidgeModel: predict before fit")
        weather = self._weather_for(timestamps[0], timestamps[-1])
        X = build_features(
            timestamps,
            self.market,
            self.unit,
            self._history,
            weather,
            use_weather=self.use_weather,
        )
        preds = self._model.predict(X[self._feature_cols])
        return pd.Series(preds, index=timestamps, name="prediction")
