"""AI Analyst: statistical engine outputs only numbers from the data, LLM
branch with verified-facts contract falls back on any violation or absence."""

import json

import pytest

from gridcast.publish import analyst


def latest_fixture():
    return {
        "generated_at": "2026-09-28T03:00:00+00:00",
        "units": {
            "KZ": {
                "champion": "naive",
                "data_through": "2026-09-28 13:00:00+00:00",
                "published_demand_tail": [
                    {"t": "2026-09-27T12:00:00+00:00", "v": 3400.0},
                    {"t": "2026-09-27T13:00:00+00:00", "v": 3600.0},
                    {"t": "2026-09-27T14:00:00+00:00", "v": 3900.0},
                ],
            },
            "IE": {
                "champion": "lightgbm",
                "data_through": "2026-09-28 12:00:00+00:00",
                "published_demand_tail": [
                    {"t": "2026-09-27T12:00:00+00:00", "v": 4500.0},
                    {"t": "2026-09-27T13:00:00+00:00", "v": 4520.0},
                ],
            },
        },
        "units_meta": {
            "KZ": {
                "unit": "KZ",
                "display_name": "Kazakhstan - North-South zone",
                "caveat": "Clearing-trade demand (~25-45% of physical consumption).",
            },
            "IE": {
                "unit": "IE",
                "display_name": "Ireland",
                "caveat": "Northerly islands co-modeled.",
            },
        },
        "degraded": [],
    }


def history_fixture():
    return {
        "days": [
            {
                "date": "2026-09-27",
                "units": {
                    "KZ": {
                        "champion": "naive",
                        "points_short": [
                            {"t": "2026-09-27T12:00:00+00:00", "pred": 3500.0, "lo90": 3000.0, "hi90": 4000.0},
                            {"t": "2026-09-27T13:00:00+00:00", "pred": 3700.0, "lo90": 3200.0, "hi90": 4200.0},
                            {"t": "2026-09-27T14:00:00+00:00", "pred": 4000.0, "lo90": 3500.0, "hi90": 4500.0},
                        ],
                    },
                    "IE": {
                        "champion": "lightgbm",
                        "points_short": [
                            {"t": "2026-09-27T12:00:00+00:00", "pred": 4600.0, "lo90": 4000.0, "hi90": 5000.0},
                            {"t": "2026-09-27T13:00:00+00:00", "pred": 4500.0, "lo90": 4100.0, "hi90": 4900.0},
                        ],
                    },
                },
            }
        ]
    }


def metrics_fixture():
    return {
        "units": {
            "KZ": {
                "champion_model": "seasonal-naive-168h",
                "primary_metric": "mape_pct",
                "champion_value": 4.5,
                "naive_value": 4.5,
            },
            "IE": {
                "champion_model": "lightgbm-weather",
                "primary_metric": "mape_pct",
                "champion_value": 2.0,
                "naive_value": 3.0,
            },
        }
    }


def test_statistical_engine_uses_real_numbers_only():
    out = analyst.statistical_insight(latest_fixture(), history_fixture(), metrics_fixture())
    assert out["mode"] == "statistical"
    head = out["items"][0]["headline"]
    mean_delta = ((3.0 - 2.0) + (4.5 - 4.5)) / 2.0
    assert f"{mean_delta:.2f}" in head
    body = out["items"][0]["body"]
    # biggest miss: ref frame pred 4000 vs published v 3900 -> 100.0 MW on KZ first?
    assert "units watching" not in head
    assert out["items"][0]["rating"] in ("strong day", "steady day", "mixed day", "watch list")
    # every number in the output traceable to inputs
    facts = out["facts_for_review"]
    assert facts["days_n"] == 1
    assert facts["rating_rows"][0]["delta"] == pytest.approx(0.0)  # KZ: naive ties
    assert facts["rating_rows"][1]["delta"] == pytest.approx(1.0)  # IE: GBM ahead
    assert facts["yesterday_misses"][0]["abs_err_mw"] == pytest.approx(100.0)
    assert facts["yesterday_misses"][0]["unit"] == "KZ"


def test_llm_disabled_key_absent_returns_statistical(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    out = analyst.llm_insight(latest_fixture(), history_fixture(), metrics_fixture())
    assert out["mode"] == "statistical"
    assert out["llm_note"].startswith("no LLM_API_KEY")


def test_llm_bad_numbers_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    fake = json.dumps({"headline": "GB demand is 999999 MW", "body": "crazy", "rating": "strong day"})

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": fake}}]}

    monkeypatch.setattr(analyst.requests, "post", lambda *a, **kw: _Resp())
    out = analyst.llm_insight(latest_fixture(), history_fixture(), metrics_fixture())
    assert out["mode"] == "statistical"
    assert "unsupported numbers" in out["llm_note"]


def test_llm_transport_error_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    def _raise(*a, **kw):
        raise analyst.requests.ConnectionError("offline here")

    monkeypatch.setattr(analyst.requests, "post", _raise)
    out = analyst.llm_insight(latest_fixture(), history_fixture(), metrics_fixture())
    assert out["mode"] == "statistical"
    assert "transport error" in out["llm_note"]


def test_llm_valid_llm_used(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    # numbers chosen to exist verbatim in the fixture facts (2.0 delta, 2 units, 1 days_n);
    # this is exactly the anti-hallucination contract passing FOR a good answer.
    fake = json.dumps(
        {
            "headline": "Champions held the line by 2.0 pts across 2 units.",
            "body": "Steady 1-day streak, IE ahead; treat 2026-09-27 as normal day.",
            "rating": "strong day",
        }
    )

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": fake}}]}

    monkeypatch.setattr(analyst.requests, "post", lambda *a, **kw: _Resp())
    out = analyst.llm_insight(latest_fixture(), history_fixture(), metrics_fixture())
    assert out["mode"] == "llm"
    assert out["items"][0]["headline"] == "Champions held the line by 2.0 pts across 2 units."
    assert out["items"][0]["rating"] == "strong day"
