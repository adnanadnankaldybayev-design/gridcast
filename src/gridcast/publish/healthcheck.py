"""Daily health gate for the dashboard data.

A unit fails when its published tail is older than the unit's OWN operator
publication lag plus slack — a flat limit is wrong by design here: GB
legitimately publishes ~21 days late and DK ~18, so a single threshold either
false-alarms them daily or ignores real stalls on the near-real-time markets.

Usage: python -m gridcast.publish.healthcheck site/data/latest_forecasts.json
Exit 0 = healthy, 1 = degraded units or stale data (message on stdout).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from gridcast.eval.backtest import PUB_LAG_DAYS

SLACK_HOURS = 48.0  # operator batching pauses, weekends, clock skew


def find_stale(
    latest: dict, now: datetime, slack_h: float = SLACK_HOURS
) -> list[tuple[str, float, float]]:
    """(unit, age_h, limit_h) for units older than their market's lag + slack."""
    out = []
    for unit, snap in latest.get("units", {}).items():
        market = snap.get("market", unit)
        limit_h = PUB_LAG_DAYS.get(market, 1.0) * 24 + slack_h
        through = datetime.fromisoformat(str(snap["data_through"]).replace("Z", "+00:00"))
        age_h = (now - through).total_seconds() / 3600
        if age_h > limit_h:
            out.append((unit, round(age_h, 1), round(limit_h, 1)))
    return out


def main(argv: list[str] | None = None) -> int:
    path = Path((sys.argv[1:] if argv is None else argv)[0])
    latest = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    degraded = latest.get("degraded") or []
    stale = find_stale(latest, now)
    if degraded or stale:
        print("HEALTHCHECK FAIL:", "degraded:", degraded, "stale:", stale)
        return 1
    print(f"HEALTHCHECK OK: {len(latest.get('units', {}))} units, issue {latest.get('issue')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
