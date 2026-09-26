"""Contract tests for the NESO adapter, on fixtures carved from the real
yearly CSVs (data/raw, 2026-09-26). The fixtures pin the two formats in the
wild: 2026+ files carry FORECAST_ACTUAL_INDICATOR, older files are quoted and
actuals-only, and DST days have 46 / 50 settlement periods."""

from datetime import date

import pandas as pd

from conftest import read_fixture
from gridcast.ingest import neso


def test_parse_2026_slice_rows_and_first_values():
    df = neso.parse_csv(read_fixture("neso_demanddata_2026_dst_slice.csv"))
    assert len(df) == 48 + 46  # 2026-01-01 + short DST day 2026-03-29
    first = df.iloc[0]
    assert first["timestamp"] == pd.Timestamp("2026-01-01 00:00", tz="UTC")
    assert first["demand_mw"] == 25107  # ND of SP1, real value
    assert df["forecast_mw"].isna().all()


def test_parse_2026_spring_dst_is_continuous_elapsed_time():
    df = neso.parse_csv(read_fixture("neso_demanddata_2026_dst_slice.csv"))
    ts = df["timestamp"].reset_index(drop=True)
    day = ts[ts.dt.date == date(2026, 3, 29)]
    assert len(day) == 46
    # 46 adjacent 30-min UTC slots: no hole, no duplicate across the switch
    assert (day.diff().dropna() == pd.Timedelta(minutes=30)).all()


def test_parse_quoted_actuals_only_format_2025():
    df = neso.parse_csv(read_fixture("neso_demanddata_2025_autumn_dst.csv"))
    assert len(df) == 50  # long DST day
    ts = df["timestamp"].reset_index(drop=True)
    assert (ts.diff().dropna() == pd.Timedelta(minutes=30)).all()
    # local midnight 2025-10-26 is BST (UTC+1) -> 2025-10-25 23:00 UTC
    assert ts.iloc[0] == pd.Timestamp("2025-10-25 23:00", tz="UTC")


def test_resource_name_year_extraction(monkeypatch):
    payload = {
        "success": True,
        "result": {
            "resources": [
                {
                    "name": "Historic Demand Data 2026",
                    "format": "CSV",
                    "url": "https://example/2026.csv",
                },
                {"name": "FAQ", "format": "DOC", "url": "https://example/faq.docx"},
            ]
        },
    }

    class FakeSession:
        def get(self, url, **kwargs):
            import json

            class Resp:
                status_code = 200
                content = json.dumps(payload).encode()

            return Resp()

    urls = neso.resource_urls(session=FakeSession())
    assert urls == {2026: "https://example/2026.csv"}
