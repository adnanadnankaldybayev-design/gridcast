"""Regression tests for the E9 G3 review fixes:

1. daily healthcheck staleness limits are PER-MARKET (GB ~21d / DK ~18d
   publication lags are the norm, not a stall) — the flat 6-day limit in the
   first daily.yml would have failed every run and blocked every deploy.
2. unit_weather_forecast must read the true UTC clock: a naive local
   datetime labeled as UTC drops the first hours of the NWP forecast on any
   non-UTC host.
"""

import json
from datetime import UTC, datetime

import pandas as pd

import gridcast.features.weather as weather_mod
from gridcast.publish.healthcheck import find_stale
from gridcast.publish.healthcheck import main as health_main


def _snap(market, unit, age_days, issue="2026-09-27T12:00:00+00:00"):
    through = pd.Timestamp(issue) - pd.Timedelta(days=age_days)
    return {
        "issue": issue,
        "units": {
            unit: {
                "market": market,
                "unit": unit,
                "data_through": through.isoformat(),
            }
        },
        "degraded": [],
    }


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_stale_limits_are_per_market():
    # GB published tail 22 days old is NORMAL (21d lag) -> not stale
    assert find_stale(_snap("GB", "GB", 22), NOW) == []
    # DK 19.5 days old is normal (18d lag) -> not stale
    assert find_stale(_snap("DK", "DK", 19.5), NOW) == []
    # ...but a genuinely stalled GB (24d = lag 21d + 48h slack + margin) fails
    assert find_stale(_snap("GB", "GB", 24), NOW) != []
    # IE near-real-time: 3 days old IS a stall (limit 6h + 48h)
    assert find_stale(_snap("IE", "ALL", 3), NOW) != []
    # IE fresh passes
    assert find_stale(_snap("IE", "ALL", 1), NOW) == []


def test_health_main_exit_codes(tmp_path, capsys):
    # main() reads the wall clock: ages must be relative to real now, else the
    # test turns into a time bomb at the next boundary crossing (caught 2026-09-28)
    now = datetime.now(UTC)

    def fresh_snap(market, unit, age_days):
        through = now - pd.Timedelta(days=age_days)
        return {
            "issue": now.isoformat(),
            "units": {unit: {"market": market, "unit": unit, "data_through": through.isoformat()}},
            "degraded": [],
        }

    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(fresh_snap("GB", "GB", 22)))
    assert health_main([str(ok)]) == 0

    bad = tmp_path / "bad.json"
    payload = fresh_snap("IE", "ALL", 5)
    payload["degraded"] = [{"unit": "FR", "error": "boom"}]
    bad.write_text(json.dumps(payload))
    assert health_main([str(bad)]) == 1
    assert "HEALTHCHECK FAIL" in capsys.readouterr().out


class _FakeSession:
    def __init__(self, payload: bytes):
        self._payload = payload

    def get(self, url, **kwargs):
        import types

        return types.SimpleNamespace(status_code=200, content=self._payload, url=url)


def _forecast_payload(start: pd.Timestamp | None = None):
    # relative-to-now by default: tests filtering against real UTC now must not
    # rot on the next date rollover (caught: frozen payload aged out overnight)
    start = start or (pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=1))
    hours = pd.date_range(start, periods=72, freq="h")  # naive strings
    return json.dumps(
        {
            "hourly": {
                "time": [t.strftime("%Y-%m-%dT%H:%M") for t in hours],
                "temperature_2m": [10.0] * 72,
                "relative_humidity_2m": [50.0] * 72,
                "wind_speed_10m": [5.0] * 72,
            }
        }
    ).encode()


def test_forecast_filter_uses_true_utc_not_local_wallclock(monkeypatch):
    """Simulate a UTC+5 host: naive local wall time 15:34 while true UTC is
    10:34. The old code labeled 15:34 as UTC and dropped 5 forecast hours."""

    class FakeDatetime:
        @staticmethod
        def now(tz=None):
            if tz is None:  # the buggy call path
                return datetime(2026, 9, 27, 15, 34)  # local wall clock (UTC+5)
            return datetime(2026, 9, 27, 10, 34, tzinfo=UTC)  # true UTC

    monkeypatch.setattr(weather_mod, "datetime", FakeDatetime)
    session = _FakeSession(_forecast_payload(pd.Timestamp("2026-09-27")))
    out = weather_mod.unit_weather_forecast("ALL", 48, session=session)
    assert out.index[0] == pd.Timestamp("2026-09-27 10:00", tz="UTC")
    assert str(out.index.tz) == "UTC"


class _PartiallyDeadSession:
    """Fake session: raises ConnectionError for chosen point latitudes."""

    def __init__(self, payload: bytes, dead_lats: set):
        self._payload = payload
        self._dead = dead_lats

    def get(self, url, **kwargs):
        import types

        import requests

        if kwargs["params"]["latitude"] in self._dead:
            raise requests.ConnectionError("simulated point outage")
        return types.SimpleNamespace(status_code=200, content=self._payload, url=url)


def test_forecast_tolerates_partial_point_outage():
    """One hanging weather point must NOT kill the whole unit's forecast
    (Open-Meteo nightly overload tolerated point-by-point, whole run lives)."""
    session = _PartiallyDeadSession(_forecast_payload(), dead_lats={51.5074})
    out = weather_mod.unit_weather_forecast("GB", 48, session=session)
    assert str(out.index.tz) == "UTC"
    assert len(out) > 0
    assert all(c.startswith("w_") for c in out.columns)


def test_forecast_raises_when_all_points_dead():
    """Total weather outage still surfaces honestly: the unit degrades instead
    of silently predicting without weather data."""
    import pytest

    from gridcast.ingest.base import IngestError

    session = _PartiallyDeadSession(
        _forecast_payload(), dead_lats={51.5074, 53.4808, 55.8642}
    )
    with pytest.raises(IngestError, match="all 3 points failed"):
        weather_mod.unit_weather_forecast("GB", 48, session=session)


def test_healthcheck_tolerates_source_stall_dk(monkeypatch, tmp_path, capsys):
    """DK upstream itself hasn't published past our data_through → degrade
    (warning, exit 0), not a hard fail that blocks the whole daily deploy."""
    from datetime import timedelta as _td

    through = datetime.now(UTC) - _td(hours=496)
    latest = {
        "issue": datetime.now(UTC).isoformat(),
        "units": {
            "DK": {
                "market": "DK",
                "champion": "naive",
                "data_through": through.isoformat(),
            }
        },
    }
    p = tmp_path / "latest.json"
    import json as _json

    p.write_text(_json.dumps(latest), encoding="utf-8")
    import gridcast.publish.healthcheck as hc

    monkeypatch.setattr(hc, "source_newest_dk", lambda: through)
    assert hc.main([str(p)]) == 0
    assert "source-stalled(tolerated)" in capsys.readouterr().out


def test_healthcheck_hard_fails_when_upstream_has_newer(monkeypatch, tmp_path):
    """We are stale while the operator HAS fresher data → real failure."""
    from datetime import timedelta as _td

    through = datetime.now(UTC) - _td(hours=496)
    latest = {
        "issue": datetime.now(UTC).isoformat(),
        "units": {"DK": {"market": "DK", "data_through": through.isoformat()}},
    }
    p = tmp_path / "latest.json"
    import json as _json

    p.write_text(_json.dumps(latest), encoding="utf-8")
    import gridcast.publish.healthcheck as hc

    monkeypatch.setattr(hc, "source_newest_dk", lambda: through + _td(hours=48))
    assert hc.main([str(p)]) == 1
