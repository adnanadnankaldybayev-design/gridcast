"""ChronosModel one-anchor smoke per market: GB (30-min), IE (15-min), AU (5-min)."""

import sys
import time

sys.path.insert(0, "src")

import pandas as pd

from gridcast.ingest.base import read_processed

MARKETS = {"GB": ("GB", 30), "IE": ("ALL", 15), "AU": ("NSW1", 5)}

from gridcast.models.chronos import ChronosModel
from gridcast.models.naive import SeasonalNaive


def smape(a, b):
    return 100 * (2 * (a - b).abs() / (a.abs() + b.abs())).mean()


for market, (unit, step) in MARKETS.items():
    df = read_processed(market).dropna(subset=["demand_mw"])
    s = df[df.region == unit].set_index("timestamp")["demand_mw"].sort_index()
    anchor = pd.Timestamp("2026-08-05 12:00", tz="UTC")
    lag = pd.Timedelta(days=21 if market == "GB" else 0.25)
    hist = s.loc[: anchor - lag]
    targets = pd.date_range(
        anchor + pd.Timedelta(minutes=step), anchor + pd.Timedelta(hours=48), freq=f"{step}min"
    )
    actual = s.reindex(targets)

    m = ChronosModel(market, unit)
    t0 = time.time()
    m.fit(hist)
    p = m.predict(targets)
    n = SeasonalNaive()
    n.fit(hist)
    pn = n.predict(targets)
    print(
        f"{market}/{unit} steps={len(targets)}: chronos {smape(actual, p):.2f} sMAPE, "
        f"naive {smape(actual, pn):.2f}, pred {time.time() - t0:.1f}s"
    )
