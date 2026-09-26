"""Forecast models sharing the ForecastModel protocol (E2+)."""

from gridcast.models.base import ForecastModel
from gridcast.models.naive import SeasonalNaive

__all__ = ["ForecastModel", "SeasonalNaive"]
