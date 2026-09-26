"""One-off smoke: ChronosModel on a real AU anchor (sanity of API + latency)."""

import sys
import time

sys.path.insert(0, "src")

import pandas as pd

from gridcast.eval.backtest import load_series
from gridcast.models.chronos import ChronosModel
from gridcast.models.naive import SeasonalNaive

s = load_series("AU")["NSW1"]
anchor = pd.Timestamp("2026-08-05 12:00", tz="UTC")
hist = s.loc[: anchor - pd.Timedelta(hours=6)]
targets = pd.date_range(
    anchor + pd.Timedelta(minutes=5), anchor + pd.Timedelta(hours=48), freq="5min"
)
actual = s.reindex(targets)

m = ChronosModel("AU", "NSW1")
t0 = time.time()
m.fit(hist)
p = m.predict(targets)
dt = time.time() - t0

n = SeasonalNaive()
n.fit(hist)
pn = n.predict(targets)


def smape(a, b):
    return 100 * (2 * (a - b).abs() / (a.abs() + b.abs())).mean()


print("predict time:", round(dt, 1), "s; nans:", int(p.isna().sum()), "range:", p.min().round(0), p.max().round(0))
print("chronos sMAPE:", round(smape(actual, p), 3))
print("naive   sMAPE:", round(smape(actual, pn), 3))
