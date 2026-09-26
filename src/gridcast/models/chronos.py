"""Zero-shot Chronos-Bolt forecaster (amazon/chronos-bolt-mini, CPU).

Project rules encoded here:
- ZERO-SHOT: fit() stores only context (no gradient updates, no fitting);
  the same pretrained weights run on every market.
- Publication discipline: the context is exactly the history the backtest
  engine cut at anchor - pub_lag; GB's 21-day arrears means Chronos predicts
  from equally stale context as every other model — fair by construction.
- Latency on CPU is the binding constraint; the engine's anchors_stride
  subsample keeps wall time sane (documented in reports).

Model choice: bolt-mini (smallest Bolt weight, ~20MB) — RAM-light and fast;
upgrade path to bolt-small is one config string.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MODEL_ID = "amazon/chronos-bolt-mini"
MAX_CONTEXT = 2048  # bolt context window (longer history is truncated from the left)


class _PipelineHolder:
    """Lazy singleton-ish loader so tests/backtests never pay double loads."""

    _pipeline = None

    @classmethod
    def get(cls):
        if cls._pipeline is None:
            import torch
            from chronos import BaseChronosPipeline

            cls._pipeline = BaseChronosPipeline.from_pretrained(
                MODEL_ID, device_map="cpu", torch_dtype=torch.float32
            )
            log.info("Chronos: loaded %s on CPU", MODEL_ID)
        return cls._pipeline

    @classmethod
    def set(cls, pipeline) -> None:
        cls._pipeline = pipeline


@dataclass
class ChronosModel:
    market: str
    unit: str
    context_hours: int = 24 * 21  # 3 weeks of context is plenty for weekly season
    model_id: str = MODEL_ID

    def __post_init__(self):
        self.name = "chronos-bolt-zero-shot"
        self._context: np.ndarray | None = None

    def update_history(self, history: pd.Series) -> None:
        self.fit(history)

    def fit(self, history: pd.Series) -> None:
        """Zero-shot 'fit' = cut the publication-safe context. No training."""
        hist = history.dropna()
        if len(hist) < 48:
            raise ValueError(f"ChronosModel {self.unit}: too little history ({len(hist)})")
        self._context = hist.to_numpy(dtype="float32")[-MAX_CONTEXT:]

    def predict(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        if self._context is None:
            raise RuntimeError("ChronosModel: predict before fit")
        import torch

        pipeline = _PipelineHolder.get()
        steps = len(timestamps)
        context = torch.tensor(self._context).unsqueeze(0)
        with torch.no_grad():
            forecast = pipeline.predict(context, prediction_length=steps)
        # bolt output: [batch, n_samples, steps]; point forecast = sample median.
        # accept both torch tensors and numpy arrays (stub pipelines in tests)
        samples = np.asarray(forecast)[0]
        median = np.median(samples, axis=0)
        return pd.Series(median, index=timestamps, name="prediction")
