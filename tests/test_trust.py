"""Trust-layer tests: provenance, clean-tree policy, weather cache migration,
warmup flagging, train-only cold decile."""

import json
import subprocess

import pandas as pd
import pytest

from gridcast.eval.backtest import (
    BacktestConfig,
    aggregate,
    assert_clean_tree,
    finish_report,
    git_state,
    rolling_origin,
)
from gridcast.features.weather import migrate_weather_cache
from test_backtest_engine import synth_series


def test_git_state_reports_real_sha_and_dirty():
    from gridcast.config import REPO_ROOT

    state = git_state(REPO_ROOT)
    assert len(state["git_sha"]) >= 6
    assert state["git_sha"] != "unknown"
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    assert state["git_sha"] == head
    assert isinstance(state["git_dirty"], bool)


def test_finish_report_raises_without_git(tmp_path):
    with pytest.raises(RuntimeError, match="cannot stamp report"):
        finish_report({}, tmp_path / "r.json", repo_root=tmp_path)


def test_clean_tree_policy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    assert_clean_tree(repo)  # clean: no exception
    (repo / "a.txt").write_text("changed")
    with pytest.raises(RuntimeError, match="dirty"):
        assert_clean_tree(repo)


def _fake_snapshot(path, temps):
    hourly = {"time": list(temps.index.strftime("%Y-%m-%dT%H:%M"))}
    for col in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m"):
        hourly[col] = list(temps[col])
    path.write_text(json.dumps({"hourly": hourly}), encoding="utf-8")


def test_weather_cache_migration(tmp_path):
    from gridcast.features.weather import VARIABLES

    idx1 = pd.date_range("2026-03-01", periods=24, freq="h", tz="UTC")
    idx2 = pd.date_range("2026-03-01 12:00", periods=24, freq="h", tz="UTC")  # 12h overlap
    df1 = pd.DataFrame([[1.0, 50.0, 5.0]] * len(idx1), index=idx1, columns=VARIABLES)
    df2 = pd.DataFrame([[2.0, 60.0, 6.0]] * len(idx2), index=idx2, columns=VARIABLES)
    cache = tmp_path / "weather"
    cache.mkdir()
    _fake_snapshot(cache / "20260101T000000Z_51.5074_-0.1278_2026-03-01_2026-03-01.json", df1)
    _fake_snapshot(cache / "20260102T000000Z_51.5074_-0.1278_2026-03-01_2026-03-02.json", df2)
    _fake_snapshot(cache / "20260102T000000Z_53.3498_-6.2603_2026-03-01_2026-03-02.json", df2)

    out = migrate_weather_cache(cache)
    assert out["51.5074_-0.1278"] == 24 + 12  # dedup keeps later snapshot (12 extra)
    assert out["53.3498_-6.2603"] == 24
    assert not list(cache.glob("*.json"))  # legacy deleted

    pq = pd.read_parquet(cache / "51.5074_-0.1278.parquet").set_index("timestamp")
    assert pq.index.tz is not None
    # overlapping 12:00..23:00 of day 1: the later snapshot wins
    assert pq.loc["2026-03-01 12:00:00", "temperature_2m"] == 2.0
    assert pq.loc["2026-03-01 11:00:00", "temperature_2m"] == 1.0

    # idempotent second run
    assert migrate_weather_cache(cache) == {}


def test_warmup_flag_boundary_and_post_warmup_aggregation():
    """GB main lag 672h (4 weeks) => warmup = history < 2 seasons = 56 days.
    Data from 2026-02-15, pub lag 21d:
    anchor 03-29 -> history to 03-08 (3w+) -> warmup True
    anchor 04-26 -> history to 04-05 (49d+) -> still < 56d -> True
    anchor 05-04 -> history to 04-13 (57d+) -> False"""
    s = synth_series(days=80)
    cfg = BacktestConfig(min_history_days=21)
    bt = rolling_origin(
        s,
        "GB",
        "GB",
        cfg,
        pd.Timestamp("2026-03-28", tz="UTC"),
        pd.Timestamp("2026-05-04", tz="UTC"),
    )
    assert "warmup" in bt.columns
    per_anchor = bt.groupby("anchor")["warmup"].first()
    assert per_anchor.loc[pd.Timestamp("2026-03-29 12:00", tz="UTC")]
    assert per_anchor.loc[pd.Timestamp("2026-05-02 12:00", tz="UTC")]  # 55.5d < 56d
    assert not per_anchor.loc[pd.Timestamp("2026-05-03 12:00", tz="UTC")]  # 56.5d >= 56d

    out = aggregate(bt, cfg)
    assert "overall_post_warmup" in out
    assert out["warmup_anchors"] >= 1
    assert out["n_anchors_total"] > out["warmup_anchors"]
    assert 0 < out["post_warmup_share"] < 1


def test_cold_decile_threshold_from_reference_only():
    """Threshold learned ONLY on pre-evaluation reference: heating the eval
    window must not change which days count as cold; cooling it must not
    change the threshold."""

    from gridcast.eval.slices import _cold_dates_with_provenance
    from gridcast.features.weather import POINTS, seed_point_data

    unit = "ALL"
    lat, lon, _ = POINTS[unit][0]
    # seed MUST cover the whole 90d reference + eval window, otherwise
    # point_data extends the memo from the network (by design). Seeding stores
    # a copy, so we mutate and reseed explicitly.
    idx = pd.date_range("2025-11-01", periods=200 * 24, freq="h", tz="UTC")
    temps = pd.DataFrame(
        {
            "temperature_2m": [5.0] * (150 * 24) + [20.0] * (50 * 24),
            "relative_humidity_2m": 50.0,
            "wind_speed_10m": 5.0,
        },
        index=idx,
    )
    frame = pd.DataFrame(
        {"timestamp": pd.date_range("2026-03-31", periods=10, freq="D", tz="UTC")}
    )

    seed_point_data(lat, lon, temps)
    dates, meta = _cold_dates_with_provenance(frame, unit)
    # reference = prev 90 days at 5C -> threshold ~5C; eval days at 20C -> none cold
    assert dates == set()
    assert meta["threshold_c"] == pytest.approx(5.0)
    assert meta["threshold_basis"].startswith("pre-evaluation")
    # now cool the eval days and reseed; the threshold itself must NOT move
    temps2 = temps.copy()
    temps2.loc[temps2.index >= pd.Timestamp("2026-03-31", tz="UTC"), "temperature_2m"] = 2.0
    seed_point_data(lat, lon, temps2)
    dates2, meta2 = _cold_dates_with_provenance(frame, unit)
    assert meta2["threshold_c"] == pytest.approx(meta["threshold_c"])
    # 10 UTC eval days -> 11 LOCAL Dublin dates (23:00 UTC = 00:00 next local day)
    assert len(dates2) == 11
