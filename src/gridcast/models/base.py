"""Model interface — every forecaster (naive, LightGBM, Chronos) implements
this protocol, so the eval engine never knows which model it runs."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class ForecastModel(Protocol):
    """fit on a strictly-past demand series, predict given future timestamps."""

    name: str

    def fit(self, history: pd.Series) -> None:
        """Store whatever the model needs from `history`.

        `history`: demand in MW, DatetimeIndex in UTC, strictly ordered,
        ending at the publication cutoff of the anchor being simulated.
        Models must NOT keep references to data beyond it.
        """
        ...

    def predict(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        """Forecast MW for each timestamp (all later than the fit cutoff)."""
        ...


class UpdateableHistory(Protocol):
    """Optional hook for the engine's periodic-refit mode: refresh the data
    the model reads at prediction time (lags), without re-estimating params.
    Must obey the same publication cutoff discipline as fit()."""

    def update_history(self, history: pd.Series) -> None:
        ...
