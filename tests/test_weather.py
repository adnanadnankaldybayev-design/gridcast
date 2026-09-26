"""Weather module contract tests on a real Open-Meteo snapshot (carved from
data/raw/weather, 2026-09-26), plus config integrity and weighted-mean math."""

import pandas as pd
import pytest

from conftest import read_fixture
from gridcast.features.weather import (
    POINTS,
    VARIABLES,
    parse_response,
    seed_point_data,
    unit_weather,
)


def test_parse_real_snapshot():
    df = parse_response(read_fixture("openmeteo_london_2days.json"))
    assert len(df) == 48
    assert str(df.index.tz) == "UTC"
    assert list(df.columns) == list(VARIABLES)
    assert df["temperature_2m"].between(-30, 45).all()
    assert df["relative_humidity_2m"].between(0, 100).all()


def test_parse_rejects_bad_payload():
    from gridcast.ingest.base import IngestError

    with pytest.raises(IngestError, match="unexpected payload"):
        parse_response('{"error": true, "reason": "bad request"}')


def test_points_config_integrity():
    # every known unit has points; weights sum to 1 (weighted mean semantics)
    for unit in ("GB", "ALL", "NSW1", "QLD1", "SA1", "TAS1", "VIC1", "NEM_TOTAL"):
        assert unit in POINTS
        total = sum(w for _lat, _lon, w in POINTS[unit])
        assert total == pytest.approx(1.0)


def test_weighted_mean_logic():
    """Seed the real GB points with constant temps; the unit series must be
    the exact weighted mean (London .45, Manchester .35, Glasgow .20)."""
    idx = pd.date_range("2026-03-01", periods=24, freq="h", tz="UTC")
    temps = [10.0, 20.0, 30.0]
    for (lat, lon, _w), temp in zip(POINTS["GB"], temps, strict=True):
        seed_point_data(lat, lon, pd.DataFrame(temp, index=idx, columns=list(VARIABLES)))
    w = unit_weather("GB", idx[0].date(), idx[-1].date(), session=None)
    expected = 10.0 * 0.45 + 20.0 * 0.35 + 30.0 * 0.20
    assert w["w_temperature_2m"].iloc[0] == pytest.approx(expected)
    assert str(w.index.tz) == "UTC"
