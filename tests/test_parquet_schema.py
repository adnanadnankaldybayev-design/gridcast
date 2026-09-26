"""Smoke tests for the normalized schema writer: parquet layout, dtypes and
idempotent monthly partitioning."""

import pandas as pd
import pytest

from gridcast.ingest.base import (
    SCHEMA_COLUMNS,
    IngestError,
    normalize,
    read_processed,
    write_parquet,
)


def _sample(market="GB", region="GB"):
    ts = pd.date_range("2026-03-01", periods=4, freq="30min", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "demand_mw": [100.0, 101.0, 102.0, 103.0], "forecast_mw": pd.NA}
    )


def test_normalize_schema_and_dtypes(tmp_path):
    out = normalize(_sample(), "GB", "GB", "test")
    assert list(out.columns) == SCHEMA_COLUMNS
    assert str(out["timestamp"].dtype) == "datetime64[us, UTC]"
    assert out["demand_mw"].dtype == "float64"
    assert out["forecast_mw"].dtype == "float64"


def test_write_partitions_by_month_and_is_idempotent(tmp_path):
    span = pd.date_range("2026-03-31 23:00", periods=4, freq="30min", tz="UTC")  # spans Mar/Apr
    df = normalize(
        pd.DataFrame({"timestamp": span, "demand_mw": 1.0, "forecast_mw": pd.NA}),
        "GB",
        "GB",
        "test",
    )
    written = write_parquet(df, "GB", tmp_path)
    names = sorted(p.name for p in written)
    assert names == ["demand_GB_2026-03.parquet", "demand_GB_2026-04.parquet"]

    # re-running ingest for the same window rewrites the partition, not appends
    write_parquet(df, "GB", tmp_path)
    back = read_processed("GB", tmp_path)
    assert len(back) == 4

    read_back = pd.read_parquet(tmp_path / "demand_GB_2026-03.parquet")
    assert list(read_back.columns) == SCHEMA_COLUMNS
    assert str(read_back["timestamp"].dtype) == "datetime64[us, UTC]"


def test_narrow_reingest_merges_instead_of_truncating(tmp_path):
    """A daily incremental run must not destroy the earlier part of the month."""
    grid = pd.date_range("2026-03-01", periods=48 * 31, freq="30min", tz="UTC")  # full March
    full = normalize(
        pd.DataFrame({"timestamp": grid, "demand_mw": 1.0, "forecast_mw": pd.NA}),
        "GB",
        "GB",
        "test",
    )
    write_parquet(full, "GB", tmp_path)

    late = normalize(
        pd.DataFrame(
            {"timestamp": grid[-4:], "demand_mw": [9.1, 9.2, 9.3, 9.4], "forecast_mw": pd.NA}
        ),
        "GB",
        "GB",
        "test",
    )
    write_parquet(late, "GB", tmp_path)

    back = read_processed("GB", tmp_path)
    assert len(back) == len(grid)  # old rows survived the narrow re-ingest
    assert back["demand_mw"].tail(4).tolist() == [9.1, 9.2, 9.3, 9.4]  # fresh values win
    assert back["demand_mw"].head(1).item() == 1.0
    assert not back.duplicated(subset=["timestamp", "region"]).any()


def test_failed_write_leaves_existing_partition_intact(tmp_path, monkeypatch):
    df = normalize(_sample(), "GB", "GB", "test")
    write_parquet(df, "GB", tmp_path)

    def boom(self, path, **kwargs):
        raise OSError("disk full mid-write")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError, match="disk full"):
        write_parquet(df, "GB", tmp_path)
    monkeypatch.undo()

    back = read_processed("GB", tmp_path)
    assert len(back) == 4  # original partition untouched
    assert not list(tmp_path.glob("*.tmp"))  # no temp-file litter


def test_read_processed_missing_dir_is_empty(tmp_path):
    back = read_processed("AU", tmp_path)
    assert back.empty
    assert list(back.columns) == SCHEMA_COLUMNS


def test_negative_demand_is_kept_with_warning(caplog):
    ts = pd.date_range("2026-03-01", periods=3, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"timestamp": ts, "demand_mw": [100.0, -12.5, 150.0], "forecast_mw": pd.NA}
    )
    with caplog.at_level("WARNING"):
        out = normalize(df, "AU", "SA1", "test")
    assert len(out) == 3
    assert out["demand_mw"].min() == -12.5
    assert "negative demand" in caplog.text


def test_all_null_demand_rejected():
    ts = pd.date_range("2026-03-01", periods=3, freq="5min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "demand_mw": pd.NA, "forecast_mw": 100.0})
    with pytest.raises(IngestError, match="no actual demand"):
        normalize(df, "IE", "ALL", "test")
