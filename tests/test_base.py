from datetime import date

import pandas as pd

from gridcast.ingest.base import midnight_utc, month_range, week_ranges


def test_month_range_inclusive_cross_year():
    assert month_range(date(2025, 11, 15), date(2026, 2, 1)) == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]


def test_month_range_single_month():
    assert month_range(date(2026, 4, 1), date(2026, 4, 30)) == ["2026-04"]


def test_week_ranges_cover_interval_aligned_to_end():
    ranges = week_ranges(date(2026, 3, 2), date(2026, 3, 16))
    assert ranges[0] == (date(2026, 3, 2), date(2026, 3, 8))
    assert ranges[-1] == (date(2026, 3, 16), date(2026, 3, 16))  # clipped at `end`
    assert ranges[0][1] == ranges[1][0] - pd.Timedelta(days=1)


def test_midnight_utc_is_dst_safe():
    dates = pd.Series(pd.to_datetime(["2026-03-29", "2025-10-26"]))
    out = midnight_utc(dates, "Europe/London")
    # 2026-03-29 00:00 Europe/London is GMT (before the 01:00 switch)
    assert out.iloc[0] == pd.Timestamp("2026-03-29 00:00", tz="UTC")
    # 2025-10-26 00:00 Europe/London is still BST (UTC+1) until 02:00
    assert out.iloc[1] == pd.Timestamp("2025-10-25 23:00", tz="UTC")
