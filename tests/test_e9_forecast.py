"""E9 daily-runner tests: snapshot schema contract, leak-guard, graceful
degrade. Weather is stubbed (no network); demand history is small synthetic."""

import numpy as np
import pandas as pd
import pytest

import gridcast.publish.forecast as pub
from gridcast.ingest.base import normalize, write_parquet


def _write_unit(tmp_path, market="GB", region="GB", days=70, step_min=30, base=25000.0):
    idx = pd.date_range(
        "2026-07-01", periods=days * 1440 // step_min, freq=f"{step_min}min", tz="UTC"
    )
    w = 7 * 86400
    secs = (idx - idx[0]).total_seconds()
    demand = base + 6000 * np.sin(2 * np.pi * ((secs % w) / w)) + 800 * np.sin(
        2 * np.pi * ((secs % 86400) / 86400)
    )
    df = normalize(
        pd.DataFrame({"timestamp": idx, "demand_mw": demand, "forecast_mw": pd.NA}),
        market, region, "test",
    )
    write_parquet(df, market, tmp_path)
    return idx


@pytest.fixture
def stub_weather(monkeypatch):
    """No Open-Meteo calls in tests — predict-time NWP is monkeypatched AND
    the archive points of every tested unit are seeded in-memory, so GBM fit
    (which reads unit_weather -> point_data) never reaches the network either
    (caught by a 429-flake run: suite quietly used the real API before)."""
    idx = pd.date_range("2025-12-01", periods=4000, freq="h", tz="UTC")
    cols = ["w_temperature_2m", "w_relative_humidity_2m", "w_wind_speed_10m"]
    stub = pd.DataFrame(8.0, index=idx, columns=cols)
    monkeypatch.setattr(pub, "unit_weather_forecast", lambda unit, hours, session=None: stub)

    from gridcast.features.weather import POINTS, seed_point_data

    # archive points are stored RAW (unit_weather adds the w_ prefix itself)
    archive_idx = pd.date_range("2026-01-01", periods=300 * 24, freq="h", tz="UTC")
    archive_stub = pd.DataFrame(
        8.0,
        index=archive_idx,
        columns=["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
    )
    for unit in ("GB", "FR"):
        for lat, lon, _w in POINTS[unit]:
            seed_point_data(lat, lon, archive_stub)
    return stub


def _write_markets(tmp_path):
    for market, regions in (
        ("GB", ["GB"]),
        ("FR", ["FR"]),
    ):
        for region in regions:
            _write_unit(tmp_path, market, region)


def test_snapshot_schema_contract(tmp_path, stub_weather):
    _write_markets(tmp_path)
    issue = pd.Timestamp("2026-09-05 02:00", tz="UTC")
    site = tmp_path / "site" / "data"
    snaps = tmp_path / "snaps"
    latest = pub.run_forecast(
        [("GB", "GB"), ("FR", "FR")],
        issue=issue,
        data_dir=tmp_path,
        site_dir=site,
        snapshots_dir=snaps,
    )
    assert latest["generated_at"] and latest["issue"] == issue.isoformat()
    for unit in ("GB", "FR"):
        s = latest["units"][unit]
        for key in ("champion", "data_through", "horizon_h", "points", "published_demand_tail"):
            assert key in s, key
        row = s["points"][0]
        assert set(row) == {"t", "pred", "lo80", "hi80", "lo90", "hi90"}
        assert row["lo90"] <= row["pred"] <= row["hi90"]
    for unit, expected_minutes in (("GB", 30), ("FR", 15)):
        s = latest["units"][unit]
        assert len(s["points"]) == 48 * 60 // expected_minutes
    assert latest["degraded"] == []
    import json

    latest_doc = json.loads((site / "latest_forecasts.json").read_text())
    assert set(latest_doc["units"]) == {"GB", "FR"}
    assert list(snaps.iterdir())
    hist = json.loads((site / "forecast_history.json").read_text())
    assert hist["days"] and hist["days"][0]["units"]["GB"]["horizon_mean_mw"]
    metrics = json.loads((site / "metrics.json").read_text())
    assert "generated_at" in metrics and "units" in metrics


def test_contract_v2_units_meta_and_generated_by(tmp_path, stub_weather):
    """R0 contract v2 (PROJECT_REBUILD_PLAN §1.7 note): site/data emits
    units_meta + generated_by with git provenance, ADDITIVE over v1 keys."""
    _write_markets(tmp_path)
    issue = pd.Timestamp("2026-09-05 02:00", tz="UTC")
    site = tmp_path / "site" / "data"
    latest = pub.run_forecast(
        [("GB", "GB"), ("FR", "FR")],
        issue=issue,
        data_dir=tmp_path,
        site_dir=site,
        snapshots_dir=tmp_path / "sn",
    )
    gb = latest["generated_by"]
    assert set(gb) == {"git_sha", "git_dirty", "gridcast_version"}
    assert isinstance(gb["git_sha"], str) and len(gb["git_sha"]) >= 6
    assert isinstance(gb["git_dirty"], bool)  # exposed, not silently dropped
    meta = latest["units_meta"]
    assert set(meta) == {"GB", "FR"}
    for unit in ("GB", "FR"):
        for key in (
            "display_name",
            "operator",
            "country_code",
            "flag",
            "tz",
            "cadence_min",
            "pub_lag_days",
            "primary_metric",
            "source_link",
            "caveat",
            "market",
            "unit",
        ):
            assert key in meta[unit], (unit, key)
    assert meta["GB"]["pub_lag_days"] == 21.0
    assert meta["FR"]["market"] == "FR"
    assert meta["GB"]["tz"] == "Europe/London"
    assert meta["FR"]["cadence_min"] == 15

    import json

    metrics_doc = json.loads((site / "metrics.json").read_text())
    assert "generated_by" in metrics_doc and "units_meta" in metrics_doc

    extract = json.loads((site / "benchmark_extract.json").read_text())
    assert "units" in extract and "git_sha" in extract


def test_leak_guard_cutoff_respected(tmp_path, stub_weather):
    """Corrupting data after (issue - pub_lag) must NOT change predictions."""
    _write_markets(tmp_path)
    issue = pd.Timestamp("2026-09-05 02:00", tz="UTC")
    units = (("GB", "GB"), ("FR", "FR"))
    before = {
        u: pub.forecast_unit(m, u, issue, tmp_path)["points"][10] for m, u in units
    }

    import glob

    from gridcast.eval.backtest import PUB_LAG_DAYS

    for f in glob.glob(str(tmp_path / "demand_*_2026-09.parquet")):
        market = f.split("demand_")[1].split("_")[0]
        df = pd.read_parquet(f)
        # corrupt ONLY what the market's own pub lag says is unpublished yet
        mask = df["timestamp"] > (issue - pd.Timedelta(days=PUB_LAG_DAYS[market]))
        df.loc[mask, "demand_mw"] = df.loc[mask, "demand_mw"] * 50
        df.to_parquet(f, index=False)

    after = {
        u: pub.forecast_unit(m, u, issue, tmp_path)["points"][10] for m, u in units
    }
    assert before == after


def test_graceful_degrade_on_unknown_unit(tmp_path, stub_weather):
    _write_markets(tmp_path)
    latest = pub.run_forecast(
        [("GB", "GB"), ("BE", "XX1")],
        issue=pd.Timestamp("2026-09-05 02:00", tz="UTC"),
        data_dir=tmp_path,
        site_dir=tmp_path / "site" / "data",
        snapshots_dir=tmp_path / "sn",
    )
    assert "XX1" not in latest["units"]
    assert any(d["unit"] == "XX1" for d in latest["degraded"])
    assert "GB" in latest["units"]


def test_daily_yaml_valid_and_has_required_permissions():
    import yaml

    with open(".github/workflows/daily.yml", encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    on = d.get("on") or d.get(True)  # YAML 1.1: bare `on:` parses as boolean True
    assert on["schedule"][0]["cron"] and on["workflow_dispatch"] is None
    perms = d["permissions"]
    assert perms.get("contents") == "write"
    steps = d["jobs"]["ingest-forecast-publish"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("Healthcheck" in n for n in names)
    assert any("Upload Pages" in n for n in names)


def test_ensemble_dedup_identity_golden(tmp_path, stub_weather):
    """Residuals are computed once per unit (E9-hot-path dedupe); the weighted
    forecast and intervals must stay bit-identical to the pre-dedupe golden
    values (pinned from the real pipeline on this fixture)."""
    _write_markets(tmp_path)
    issue = pd.Timestamp("2026-09-05 02:00", tz="UTC")
    snap = pub.forecast_unit("GB", "GB", issue, tmp_path)
    # pinned under the deterministic archive stub above (offline; the previous
    # numbers silently depended on the real on-disk weather cache)
    assert snap["weights"] == pytest.approx(
        {"naive": 0.0, "ridge": 0.0069, "lightgbm": 0.9931}, abs=1e-4
    )
    p10 = snap["points"][10]
    assert p10["pred"] == pytest.approx(26807.9, abs=0.5)
    assert p10["lo90"] == pytest.approx(26757.6, abs=0.5)
    assert p10["hi90"] == pytest.approx(26858.2, abs=0.5)
    assert len(snap["points"]) == 96


def test_incremental_start_uses_last_parquet_timestamp(tmp_path):
    from datetime import date

    from gridcast.cli import _incremental_start

    _write_unit(tmp_path, "GB", "GB", days=10)
    start = _incremental_start("GB", tmp_path, date(2026, 3, 1))
    # last parquet day is 2026-07-10 (10 days from 2026-07-01); minus 2d overlap
    assert start == date(2026, 7, 8)
    # empty dir -> full default
    assert _incremental_start("FR", tmp_path, date(2026, 3, 1)) == date(2026, 3, 1)
