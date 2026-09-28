"""AI Analyst - daily short narrative about GridCast data, in two modes.

(1) Statistical (deterministic, always available): computes facts directly
from our own bundles - yesterday's biggest hourly miss per unit, day rating
(champion minus naive), short trend, and a rotating data fact from
units_meta. Text is a small template around numbers that are guaranteed to
come from the data.

(2) LLM (optional, graceful): if LLM_API_KEY (+LLM_BASE_URL, OpenAI-compatible
chat-completions) is set, the same structured facts go to the model with an
anti-hallucination contract (only numbers present in the facts are allowed).
Every number in the answer is checked against the facts verbatim; any
mismatch, transport error, timeout, or style violation falls back to (1)
with an explicit note - never a silent hallucination.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

import requests

log = logging.getLogger(__name__)

LLM_TIMEOUT_S = 45
LLM_MODEL_DEFAULT = "gpt-4o-mini"
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)*%?")

RATING_ORDER = (
    (1.0, "strong day"),
    (0.25, "steady day"),
    (0.0, "mixed day"),
)


def _fmt_metric(v: float) -> str:
    return f"{v:.2f}"


def gather_facts(latest: dict, history: dict, metrics_json: dict) -> dict:
    """Assemble ONLY numbers available natively from our bundles.

    Returns dicts of (unit -> facts) for headline generation; each fact item
    carries the exact number so verification can compare strings later.
    """
    facts: dict[str, dict] = {}
    units_meta = latest.get("units_meta", {})

    # day rating scores per unit
    rows = []
    for unit in (latest.get("units") or {}):
        m = (metrics_json.get("units") or {}).get(unit)
        delta = None
        if m:
            delta = m["naive_value"] - m["champion_value"]
        rows.append({"unit": unit, "champion_value": m["champion_value"] if m else None,
                     "naive_value": m["naive_value"] if m else None, "delta": delta})
    facts["rating_rows"] = rows

    # yesterday-to-forward misses: compare yesterday's sparse forecast points
    # against TODAY's published tail, timestamps inner-joined
    days = history.get("days") or []
    if days:
        yday = days[-1]
        misses = []
        for unit, entry in (yday.get("units") or {}).items():
            snap = (latest.get("units") or {}).get(unit)
            tail = {(p["t"], p["v"]) for p in snap.get("published_demand_tail", [])}
            tail_map = dict(tail)
            errs = [
                (p["t"], abs(p["pred"] - tail_map[p["t"]]))
                for p in entry.get("points_short", [])
                if p["t"] in tail_map
            ]
            if errs:
                t_max, err_max = max(errs, key=lambda p: p[1])
                misses.append({"unit": unit, "hour": t_max, "abs_err_mw": round(err_max, 1)})
        facts["yesterday_misses"] = sorted(misses, key=lambda r: -r["abs_err_mw"])

    # week-to-stale tradition: crude streak
    facts["days_n"] = len(days)

    # rotation fact from units_meta by date
    idx = int(date.today().toordinal()) % max(1, len(units_meta))
    u = sorted(units_meta)[idx] if units_meta else None
    facts["fact_unit"] = u
    facts["fact_text"] = units_meta[u]["caveat"] if u else ""

    return facts


def _rating(delta_mean: float | None) -> str:
    if delta_mean is None:
        return "insufficient data"
    for lim, label in RATING_ORDER:
        if delta_mean > lim:
            return label
    return "watch list"


def statistical_insight(latest: dict, history: dict, metrics_json: dict) -> dict:
    """Deterministic analyst: every sentence carries a verifiable number."""
    facts = gather_facts(latest, history, metrics_json)
    deltas = [r["delta"] for r in facts["rating_rows"] if r["delta"] is not None]
    mean_delta = sum(deltas) / len(deltas) if deltas else None
    if mean_delta is None:
        # empty/unreadable metrics bundle: degrade to a jargon-free note instead
        # of formatting None inside the headline
        miss = (facts.get("yesterday_misses") or [None])[0]
        return {
            "mode": "statistical",
            "items": [
                {
                    "headline": "Benchmark bundle fresh-quota pending — digest resumes tomorrow.",
                    "body": (
                        f"Biggest miss yesterday: {miss['unit']} — {miss['abs_err_mw']} MW. "
                        if miss
                        else "No forecast-past-day overlap yet. "
                    )
                    + f"Running {facts['days_n']} consecutive daily issues.",
            "rating": "insufficient data",
            "basis": {"units": 0, "wins": 0, "mean_delta_pp": None,
                      "biggest_miss": miss, "streak_days": facts["days_n"]},
                }
            ],
            "facts_for_review": facts,
        }
    wins = [r for r in facts["rating_rows"] if (r["delta"] or 0) > 0]
    ties = [r for r in facts["rating_rows"] if r["delta"] is not None and r["delta"] <= 0]

    miss = facts["yesterday_misses"][0] if facts.get("yesterday_misses") else None
    items = []
    rating = _rating(mean_delta)
    if miss:
        headline = (
            f"Model beat the naive baseline by {_fmt_metric(mean_delta)} pct pts on average across "
            f"{len(wins)} of {len(deltas)} units."
        )
        body = (
            f"Biggest miss yesterday: {miss['unit']} at {miss['hour']} — off by "
            f"{miss['abs_err_mw']} MW. "
        )
    else:
        mean_text = _fmt_metric(mean_delta)
        headline = f"Champions beat naive by {mean_text} pts on average over {len(deltas)} units."
        body = "No forecast-past-day overlap yet (publication lags slow the fact view). "
    if ties:
        body += f"Oldest-tied units watching closely: {', '.join(r['unit'] for r in ties[:4])}. "
    body += f"Running {facts['days_n']} consecutive daily issues."

    items.append(
        {
            "headline": headline,
            "body": body,
            "rating": rating,
            "basis": {
                "units": len(deltas),
                "wins": len(wins),
                "mean_delta_pp": round(mean_delta, 3) if mean_delta is not None else None,
                "biggest_miss": miss,
                "streak_days": facts["days_n"],
            },
        }
    )
    if facts["fact_text"]:
        items.append(
            {
                "headline": f"Datum of the day · {facts['fact_unit']}",
                "body": facts["fact_text"],
                "rating": "context",
                "basis": {"unit": facts["fact_unit"]},
            }
        )
    return {
        "mode": "statistical",
        "items": items,
        "facts_for_review": facts,
    }


def _numbers_in(text: str) -> set[str]:
    return set(_NUM_RE.findall(text))


def _to_float(token: str) -> float | None:
    try:
        f = float(token.replace(",", "."))
        return f
    except ValueError:
        return None


def _facts_numbers(facts) -> set[float]:
    """Canonical numeric universe of the facts: every numeric leaf value plus
    every float carved out of fact strings (timestamps, measures), verbatim."""
    out: set[float] = set()
    if isinstance(facts, dict):
        for v in facts.values():
            out |= _facts_numbers(v)
    elif isinstance(facts, (list, tuple)):
        for v in facts:
            out |= _facts_numbers(v)
    elif isinstance(facts, (int, float)):
        out.add(float(facts))
    elif isinstance(facts, str):
        for tok in _numbers_in(facts):
            f = _to_float(tok)
            if f is not None:
                out.add(f)
    return out


def _verify_llm(facts: dict, out: dict) -> list[str]:
    """Return list of unsupported numbers found in the LLM output (empty if clean)."""
    allowed = _facts_numbers(facts)
    blob = json.dumps(out, ensure_ascii=False)
    support = []
    for tok in _numbers_in(blob):
        f = _to_float(tok)
        if f is not None and f not in allowed:
            support.append(tok)
    return support


def llm_insight(latest: dict, history: dict, metrics_json: dict) -> dict:
    """LLM branch with hard verification + graceful fallback to statistical."""
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", LLM_MODEL_DEFAULT)
    statue = statistical_insight(latest, history, metrics_json)
    if not api_key:
        statue["llm_note"] = "no LLM_API_KEY set - statistical mode"
        return statue

    facts = statue["facts_for_review"]
    contract = (
        '{"headline": str, "body": str, '
        '"rating": "strong day|steady day|mixed day|watch list"}'
    )
    prompt = (
        "You are an energy-market analyst for GridCast, whose numbers must come ONLY "
        "from the facts JSON below. Rules: no invented numbers; every numeric token in "
        "your answer must appear in the facts; hedged language otherwise. Respond ONLY "
        f"with JSON: {contract}.\n\n"
        f"facts:\n{json.dumps(facts, ensure_ascii=False, indent=1)}"
    )
    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "Meticulous data-fidelity analyst."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=LLM_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        log.warning("LLM transport failed (%s), statistical fallback", exc)
        statue["llm_note"] = f"transport error: {exc.__class__.__name__}; statistical mode"
        return statue
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, json.JSONDecodeError, TypeError):
        log.warning("LLM returned unparseable payload %s", resp.status_code)
        statue["llm_note"] = f"llm parse failure ({resp.status_code}); statistical mode"
        return statue

    nums_needed = _verify_llm(facts, parsed)
    if nums_needed:
        log.warning("LLM used unsupported numbers %s -> statistical fallback", nums_needed)
        statue["llm_note"] = f"unsupported numbers {nums_needed[:4]}; statistical mode"
        return statue

    allowed_ratings = {label for _lim, label in RATING_ORDER} | {"watch list"}
    try:
        fields = (parsed["headline"], parsed["body"], parsed["rating"])
    except (KeyError, TypeError) as exc:
        # valid JSON missing the contract fields (e.g. {}) — fallback, not a crash
        log.warning("LLM answer misses contract fields (%s) -> statistical fallback", exc)
        statue["llm_note"] = f"contract fields missing ({exc}); statistical mode"
        return statue
    if fields[2] not in allowed_ratings:
        log.warning("LLM rating %r outside the enum -> statistical fallback", fields[2])
        statue["llm_note"] = f"rating {fields[2]!r} not in contract enum; statistical mode"
        return statue
    if not all(isinstance(f, str) and f.strip() for f in fields):
        log.warning("LLM contract fields not non-empty strings -> statistical fallback")
        statue["llm_note"] = "contract fields empty/not strings; statistical mode"
        return statue

    items = statue["items"].copy()
    items[0] = {
        "headline": fields[0],
        "body": fields[1],
        "rating": fields[2],
        "basis": items[0]["basis"],
    }
    return {
        "mode": "llm",
        "model": model,
        "items": items,
        "facts_for_review": facts,
        "llm_note": f"LLM ({model}) over verified facts",
    }


def generate_insights(latest: dict, history: dict, metrics_json: dict) -> dict:
    from datetime import UTC, datetime

    base = llm_insight(latest, history, metrics_json)
    return {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        **base,
    }
