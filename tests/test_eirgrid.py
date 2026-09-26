"""Contract tests for the EirGrid adapter on real RSC flight payloads saved
2026-09-26 (weeks of 2026-06-01, 2026-03-23..29 spring DST, 2025-10-20..26
autumn DST). The payload embeds several "data" arrays; extract_series must
pick the demand chart series by the 'actualDemand' key."""

import pandas as pd
import pytest

from conftest import read_fixture
from gridcast.ingest import eirgrid
from gridcast.ingest.base import IngestError


def test_extract_series_picks_demand_not_yearly_stats():
    rows = eirgrid.extract_series(read_fixture("eirgrid_week_2026-06-01.rsc.txt"))
    assert len(rows) == 672  # full week of 15-min intervals
    assert rows[0] == {
        "date": "01-Jun-2026 00:00:00",
        "actualDemand": 3917,
        "forecastDemand": None,
    }


def test_parse_normal_week_utc_grid():
    df = eirgrid.parse_payload(read_fixture("eirgrid_week_2026-06-01.rsc.txt"))
    assert len(df) == 672
    assert df["timestamp"].iloc[0] == pd.Timestamp("2026-06-01 00:00", tz="UTC")
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(minutes=15)).all()
    assert df["demand_mw"].between(1000, 10000).all()


@pytest.mark.parametrize(
    "fixture",
    ["eirgrid_week_spring_dst_2026-03-23.rsc.txt", "eirgrid_week_autumn_dst_2025-10-20.rsc.txt"],
)
def test_dst_weeks_have_full_daily_grids(fixture):
    """Labels sit on a full 24h grid even on DST-change Sundays."""
    df = eirgrid.parse_payload(read_fixture(fixture))
    per_day = df.groupby(df["timestamp"].dt.date).size()
    assert len(per_day) == 7
    assert (per_day >= 91).all()  # spring week lost 4 real measurements (nulls)


def test_null_actuals_are_dropped_from_demand():
    df = eirgrid.parse_payload(read_fixture("eirgrid_week_spring_dst_2026-03-23.rsc.txt"))
    assert len(df) == 668  # 672 slots - 4 real 'actualDemand: null'
    assert df["demand_mw"].notna().all()


def test_payload_without_demand_series_raises():
    with pytest.raises(IngestError, match="actualDemand"):
        eirgrid.parse_payload('{"fancy": "html", "data": [{"year": 2020, "percent": 1.5}]}')
