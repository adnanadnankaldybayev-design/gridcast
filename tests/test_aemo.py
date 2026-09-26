"""Contract tests for the AEMO adapter on a real slice of
PRICE_AND_DEMAND_202608_NSW1.csv (header + first 120 rows of the raw file).

NEM market time is fixed UTC+10 with no DST: the first settlement interval of
2026-08-01 (00:05 market time) is 2026-07-31 14:05 UTC.
"""

import pandas as pd
import pytest

from conftest import read_fixture
from gridcast.ingest import aemo
from gridcast.ingest.base import IngestError


def test_parse_real_slice_utc_offset():
    df = aemo.parse_csv(read_fixture("aemo_price_and_demand_202608_NSW1_slice.csv"), "NSW1")
    assert len(df) == 120
    first = df.iloc[0]
    assert first["timestamp"] == pd.Timestamp("2026-07-31 14:05", tz="UTC")
    assert first["demand_mw"] == pytest.approx(8898.91)
    assert str(df["timestamp"].dtype) == "datetime64[us, UTC]"
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(minutes=5)).all()


def test_parse_filters_other_regions():
    text = (
        "REGION,SETTLEMENTDATE,TOTALDEMAND,RRP,PERIODTYPE\n"
        "NSW1,2026/08/01 00:05:00,9000.0,50.0,TRADE\n"
        "QLD1,2026/08/01 00:05:00,7000.0,60.0,TRADE\n"
    )
    df = aemo.parse_csv(text, "NSW1")
    assert len(df) == 1
    assert df["demand_mw"].iloc[0] == 9000.0


def test_unexpected_columns_raise():
    with pytest.raises(IngestError, match="missing"):
        aemo.parse_csv("REGION,FOO\nNSW1,1\n", "NSW1")
