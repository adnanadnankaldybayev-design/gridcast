"""Bank-holiday flags against known 2026 dates and local-time/DST correctness.

Checked facts:
- GB (England): New Year's Day Jan 1, Easter Monday Apr 6 2026 (BST day),
  Christmas Dec 25; a random working Wednesday Mar 4 is clean.
- IE: St Patrick's Day Mar 17 2026 (Dublin winter time is UTC+0, so the local
  calendar flips at 00:00 UTC).
- AU/NSW: Australia Day Jan 26 2026 (AEDT = UTC+11, flips at 13:00 UTC),
  Christmas Dec 25.
- 2026-09-26 is a Saturday; GB in September is BST (UTC+1).
"""

import pandas as pd

from gridcast.features.calendar import calendar_frame


def test_gb_new_years_day_all_flagged():
    idx = pd.date_range("2026-01-01", periods=48, freq="30min", tz="UTC")
    assert calendar_frame(idx, "GB")["is_holiday"].all()


def test_gb_easter_monday_local_day_via_dst():
    idx = pd.date_range("2026-04-05 20:00", periods=60, freq="30min", tz="UTC")
    f = calendar_frame(idx, "GB")
    local_dates = idx.tz_convert("Europe/London").date
    mon = [d == pd.Timestamp("2026-04-06").date() for d in local_dates]
    sun = [d == pd.Timestamp("2026-04-05").date() for d in local_dates]
    assert f.loc[mon, "is_holiday"].all()
    assert not f.loc[sun, "is_holiday"].any()


def test_gb_random_wednesday_is_clean():
    idx = pd.date_range("2026-03-04", periods=48, freq="30min", tz="UTC")
    f = calendar_frame(idx, "GB")
    assert not f["is_holiday"].any()
    assert not f["is_weekend"].any()


def test_ie_st_patricks_2026():
    # Dublin winter time is UTC+0: Mar 17 starts at 00:00 UTC sharp
    idx = pd.date_range("2026-03-16 22:00", periods=6, freq="h", tz="UTC")
    f = calendar_frame(idx, "ALL")
    assert f["is_holiday"].tolist() == [0, 0, 1, 1, 1, 1]


def test_nsw_australia_day_2026_aedt():
    # AEDT = UTC+11: Sydney Jan 26 spans 2026-01-25 13:00 .. 2026-01-26 12:59 UTC
    idx = pd.date_range("2026-01-25 12:00", periods=26, freq="h", tz="UTC")
    f = calendar_frame(idx, "NSW1")
    assert f["is_holiday"].tolist() == [0] + [1] * 24 + [0]


def test_nsw_christmas_not_eve_2026():
    idx = pd.date_range("2026-12-24 12:00", periods=72, freq="h", tz="UTC")
    f = calendar_frame(idx, "NSW1")
    local_dates = idx.tz_convert("Australia/Sydney").date
    dec25 = [d == pd.Timestamp("2026-12-25").date() for d in local_dates]
    dec24 = [d == pd.Timestamp("2026-12-24").date() for d in local_dates]
    assert f.loc[dec25, "is_holiday"].all()
    assert not f.loc[dec24, "is_holiday"].any()


def test_weekend_saturday_flags():
    idx = pd.date_range("2026-09-26 10:00", periods=6, freq="30min", tz="UTC")
    f = calendar_frame(idx, "GB")
    assert (f["is_weekend"] == 1).all()
    assert (f["day_of_week"] == 5).all()


def test_morning_ramp_uses_local_time_bst():
    # September in GB is BST (UTC+1): ramp 06:00-09:00 local == 05:00-08:00 UTC
    on = calendar_frame(pd.date_range("2026-09-14 05:00", periods=2, freq="30min", tz="UTC"), "GB")
    off = calendar_frame(pd.date_range("2026-09-14 04:00", periods=2, freq="30min", tz="UTC"), "GB")
    assert (on["is_morning_ramp"] == 1).all()
    assert (off["is_morning_ramp"] == 0).all()


def test_hours_on_spring_forward_day():
    # 2026-03-29 GB switch at 01:00 GMT -> 02:00 BST; local hours skip 01:xx
    idx = pd.date_range("2026-03-29 00:00", periods=8, freq="h", tz="UTC")
    hours = calendar_frame(idx, "GB")["hour_of_day"].tolist()
    assert hours == [0.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
