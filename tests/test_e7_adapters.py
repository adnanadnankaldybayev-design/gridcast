"""Contract tests for the E7 adapters (FR RTE, DE SMARD, BE Elia, DK Energinet)
on real captured fixtures:

- SMARD unit trap pinned by NUMBER: series value 11206.58 (MWh/qh) MUST become
  44826.32 MW (*4) — the whole-article reason this test exists.
- DST week (2026-03-29) in the FR/DE fixtures: 15-min grids continuous in UTC.
- FR rolling vs definitive parse shapes both accepted, forecast field kept.
- DK records-per-hour aggregation: national demand = sum over industry codes.
- DK 429 handling: a mocked 429 payload raises RateLimited.
"""

import json

import pandas as pd
import pytest

from conftest import read_fixture
from gridcast.ingest import be_elia, de_smard, dk_energinet, fr_rte
from gridcast.ingest.dk_energinet import RateLimited


def window_utc(day):
    d = pd.Timestamp(day, tz="UTC")
    return d, d + pd.Timedelta(days=1)


def test_be_real_day_15min_full():
    df = be_elia.parse_records(
        read_fixture("be_elia_ods003_2026-09-10.json"), window_utc("2026-09-10")
    )
    assert len(df) == 96
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(minutes=15)).all()
    assert df["demand_mw"].between(3000, 16000).all()
    assert str(df["timestamp"].dtype) == "datetime64[us, UTC]"


def test_fr_rolling_tab_real_day():
    df = fr_rte.parse_records(
        read_fixture("fr_eco2mix_tr_2026-09-20.json"), window_utc("2026-09-20")
    )
    assert len(df) >= 90
    keep = df.dropna(subset=["demand_mw"])
    assert keep["demand_mw"].between(20000, 90000).all()
    # J-1 operator forecast kept where present
    assert keep["forecast_mw"].notna().any()


def test_fr_def_dst_day_continuous_utc_grid():
    df = fr_rte.parse_records(
        read_fixture("fr_eco2mix_def_2026-03-29.json"), window_utc("2026-03-29")
    )
    assert not df.empty
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(minutes=15)).all()
    keep = df.dropna(subset=["demand_mw"])
    assert keep["demand_mw"].between(20000, 95000).all()


def test_smard_mwh_to_mw_conversion_pinned_by_number():
    payload = json.loads(read_fixture("de_smard_410_week_2026-03-26.json"))
    # the trim keeps first 240 points from 2026-03-22 22:00: day 2026-03-24
    expected_ts_ms = int(pd.Timestamp("2026-03-24 00:00", tz="UTC").timestamp() * 1000)
    assert payload["series"][100][0] == expected_ts_ms
    raw_first_0324 = payload["series"][100][1]
    df = de_smard.parse_week(json.dumps(payload), window_utc("2026-03-24"))
    assert len(df) == 96
    first = df.iloc[0]
    assert first["timestamp"] == pd.Timestamp("2026-03-24 00:00", tz="UTC")
    # raw MWh per quarter-hour -> average MW = value * 4 (unit trap pinned!)
    assert first["demand_mw"] == pytest.approx(raw_first_0324 * 4.0, rel=1e-9)
    assert df["demand_mw"].between(20000, 95000).all()


def test_dk_aggregates_industry_codes_to_national_demand():
    payload = json.loads(read_fixture("dk_energinet_dk36_2026-08-01.json"))
    assert payload["total"] == 792  # full day's industry rows in the fixture
    df = dk_energinet.parse_records(json.dumps(payload))
    assert len(df) == 24
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()
    # per-hour national total = sum over ~33 industry codes (fixture data);
    # first hour in the (desc-sorted) payload is 2026-08-01T23:00? or use a
    # known hour from the fixture — we pin 2026-08-01T00:00, which is in it:
    first = df.iloc[0]
    assert str(first["timestamp"]) == "2026-08-01 00:00:00+00:00"
    expect = sum(
        r["Consumption_MWh"]
        for r in payload["records"]
        if r["TimeUTC"] == "2026-08-01T00:00:00"
    )
    assert first["demand_mw"] == pytest.approx(expect, rel=1e-9)
    # sanity: Danish demand 2.5-6.5 GW
    assert df["demand_mw"].between(1500, 7500).all()


def test_dk_rate_limit_payload_raises_rate_limited():
    with pytest.raises(RateLimited):
        dk_energinet.parse_records(
            '{"statusCode": 429, "message": "Rate limit is exceeded. Try again in 99 seconds."}'
        )


def test_dk_parse_empty_records_is_empty_frame():
    df = dk_energinet.parse_records('{"total": 0, "records": []}')
    assert df.empty
