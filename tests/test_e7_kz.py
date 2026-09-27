"""Contract tests for the KOREM (Kazakhstan) adapter on real fixtures:

- zone-1 recent week: hourly grid, MW magnitudes (hundreds-thousands, NOT GW).
- zone-2 fixture spans the 2024-03-01 legal offset change (UTC+6 -> UTC+5):
  timestamps must remain monotone and map to the right UTC instants.
"""

import pandas as pd
import pytest

from conftest import read_fixture
from gridcast.ingest import kz_korem
from gridcast.ingest.base import IngestError


def test_zone1_real_hours_full_day():
    df = kz_korem.parse_series(read_fixture("kz_korem_ct_zone1_2026-09-01.json"))
    assert len(df) == 72  # 3 full days * 24
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()
    assert str(df["timestamp"].dtype) == "datetime64[us, UTC]"
    # post-switch: dt label 2026-09-01T00:00 local = 2026-08-31 19:00 UTC (+5)
    assert df["timestamp"].iloc[0] == pd.Timestamp("2026-08-31 19:00", tz="UTC")
    # magnitude stays in the clearing-tade band (not physical GW scale)
    assert df["demand_mw"].between(300, 8000).all()


def test_tz_switch_2024_monotone_and_correct_utc():
    df = kz_korem.parse_series(read_fixture("kz_korem_ct_zone2_tzswitch.json"))
    assert df["timestamp"].is_monotonic_increasing
    gaps = df["timestamp"].diff().dropna()
    # one legal hole at the offset switch; everything else is hourly
    assert set(gaps.unique()) <= {pd.Timedelta(hours=1), pd.Timedelta(hours=2)}
    assert (gaps == pd.Timedelta(hours=2)).sum() == 1
    # before the switch: 2024-02-29 23:00 local = 2024-02-29 17:00 UTC (+6)
    pre = df[df["timestamp"] == pd.Timestamp("2024-02-29 17:00", tz="UTC")]
    assert len(pre) == 1
    # at/after the switch: 2024-03-01 00:00 local = 2024-02-29 19:00 UTC (+5)
    post = df[df["timestamp"] == pd.Timestamp("2024-02-29 19:00", tz="UTC")]
    assert len(post) == 1
    # and the 18:00 UTC slot is missing (legal hour lost at the switch)
    assert not (df["timestamp"] == pd.Timestamp("2024-02-29 18:00", tz="UTC")).any()


def test_bad_payload_raises():
    with pytest.raises(IngestError, match="unexpected payload"):
        kz_korem.parse_series('{"error": "deprecated"}')
