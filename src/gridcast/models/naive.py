"""Seasonal-naive baseline: forecast[t] = observed[t - season].

Fallback ladder per timestamp (documented, deterministic):
  1. same slot `season` ago,
  2. same slot k*season ago (k=2,3,...) — covers gaps like missing days,
  3. the last observed value in the fit window ("last-known" fallback),
which also covers the case where the whole seasonal lookback falls outside
the publication cutoff (e.g. GB's 21-day arrears makes "a week ago"
unpublished: k grows until the slot is published).
"""

from __future__ import annotations

import pandas as pd


class SeasonalNaive:
    def __init__(self, season_hours: int = 168, max_lookbacks: int = 8):
        self.name = f"seasonal-naive-{season_hours}h"
        self.season = pd.Timedelta(hours=season_hours)
        self.max_lookbacks = max_lookbacks
        self._history: pd.Series | None = None
        self._lookup: dict[pd.Timestamp, float] = {}

    def fit(self, history: pd.Series) -> None:
        if history.empty:
            raise ValueError("SeasonalNaive.fit: empty history")
        self._history = history
        self._lookup = history.to_dict()

    def update_history(self, history: pd.Series) -> None:
        # the "model" is its lookup table; refreshing it IS refitting (cheap)
        self.fit(history)

    def predict(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        if self._history is None:
            raise RuntimeError("SeasonalNaive: predict before fit")
        last_known = float(self._history.iloc[-1])
        values = []
        for ts in timestamps:
            value = None
            for k in range(1, self.max_lookbacks + 1):
                value = self._lookup.get(ts - k * self.season)
                if value is not None:
                    break
            values.append(float(value) if value is not None else last_known)
        return pd.Series(values, index=timestamps, name="prediction")
