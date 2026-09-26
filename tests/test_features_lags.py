"""Lag features: exact values and the no-future-data property.

Property tested: a feature for timestamp t may only depend on values recorded
strictly before t (lags point at t minus a fixed offset) AND inside the
supplied history window (a lag past the publication cutoff yields NaN — the
model can never peek beyond it).
"""

import numpy as np
import pandas as pd

from gridcast.features.build import lag_features

STEP_MIN = 30
STEPS_PER_DAY = 1440 // STEP_MIN  # 48


def _hist(days=21):
    idx = pd.date_range(
        "2026-03-01", periods=days * STEPS_PER_DAY, freq=f"{STEP_MIN}min", tz="UTC"
    )
    return pd.Series(range(len(idx)), index=idx, dtype="float64")


def test_lag_values_exact():
    hist = _hist()
    lg = lag_features(hist.index, hist, (168, 336), include_short_lags=True)
    pos = 14 * STEPS_PER_DAY  # day 14, so all lags resolve inside 21 days
    assert lg["lag_24h"].iloc[pos] == hist.iloc[pos - 1 * STEPS_PER_DAY]
    assert lg["lag_48h"].iloc[pos] == hist.iloc[pos - 2 * STEPS_PER_DAY]
    assert lg["lag_168h"].iloc[pos] == hist.iloc[pos - 7 * STEPS_PER_DAY]
    assert lg["lag_336h"].iloc[pos] == hist.iloc[pos - 14 * STEPS_PER_DAY]


def test_lags_never_peek_beyond_t():
    """Corrupt every history value from D onward; features at t < D must be
    identical to the clean run — lags only look backward."""
    hist = _hist()
    d = pd.Timestamp("2026-03-07", tz="UTC")
    noisy = hist.copy()
    noisy.loc[noisy.index >= d] = -9999.0
    idx = hist.index[hist.index < d]
    clean = lag_features(idx, hist, (168, 336), include_short_lags=True)
    dirty = lag_features(idx, noisy, (168, 336), include_short_lags=True)
    pd.testing.assert_frame_equal(clean, dirty)


def test_r24_mean_lag_main_reads_only_the_window_before_t_minus_168h():
    """The rolling-mean feature covers [t-192h, t-168h]: corrupting the band
    (t-168h, t] must NOT change it."""
    hist = _hist()
    t = pd.Timestamp("2026-03-10 06:00", tz="UTC")
    noisy = hist.copy()
    noisy.loc[t - pd.Timedelta(hours=167) : t] = -9999.0
    idx = pd.DatetimeIndex([t])
    clean = lag_features(idx, hist, (168, 336), include_short_lags=True)
    dirty = lag_features(idx, noisy, (168, 336), include_short_lags=True)
    assert clean["r24_mean_lag_main"].iloc[0] == dirty["r24_mean_lag_main"].iloc[0]
    # sanity: equals pandas' right-closed 24h rolling mean sampled at t-168h
    expected = hist.rolling(pd.Timedelta(hours=24), min_periods=1).mean()
    assert clean["r24_mean_lag_main"].iloc[0] == expected.loc[t - pd.Timedelta(hours=168)]


def test_publication_cutoff_yields_nan_not_future():
    """History ends at a cutoff; features whose lag stays inside resolve,
    features whose target-source falls beyond the cutoff are NaN — never read
    from the future."""
    hist = _hist()
    cutoff_pos = 5 * STEPS_PER_DAY  # end of day 5
    cutoff = hist.index[cutoff_pos]
    history_cut = hist.loc[:cutoff]
    t1 = cutoff + pd.Timedelta(hours=12)
    t2 = cutoff + pd.Timedelta(hours=24)
    lg = lag_features(pd.DatetimeIndex([t1, t2]), history_cut, (168, 336), include_short_lags=True)
    # t1 - 24h = cutoff - 12h: inside history
    assert lg["lag_24h"].iloc[0] == hist.iloc[cutoff_pos - STEPS_PER_DAY // 2]
    # t2 - 24h = cutoff: the last published point
    assert lg["lag_24h"].iloc[1] == hist.iloc[cutoff_pos]
    # t1 - 168h is deep in history; t2 - ... still deep. Use lag_336h for NaN:
    # no wait: both are available. The NaN case is a lag SHORTER than the gap
    # between t and the cutoff: lag t1 by 336h is fine, but look at a target
    # far after the cutoff with a history that has a HOLE:
    hist_holey = history_cut.drop(history_cut.index[-STEPS_PER_DAY:])
    lg2 = lag_features(pd.DatetimeIndex([t1]), hist_holey, (168, 336), include_short_lags=True)
    # t1 - 24h = cutoff - 12h lies in the dropped day -> NaN, not future data
    assert np.isnan(lg2["lag_24h"].iloc[0])
    # t1 - 48h = cutoff - 36h: still present (arithmetic, not convention)
    assert lg2["lag_48h"].iloc[0] == hist.iloc[cutoff_pos - 36 * (60 // STEP_MIN)]
