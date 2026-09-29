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
from datetime import UTC, datetime, timedelta
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


def source_newest_dk() -> datetime | None:
    """Freshest timestamp Energinet currently offers for national consumption.

    Their hourly datasets stalled as a whole (checked 2026-09-29: every
    national consumption series stops at 2026-09-08). A source stall must
    degrade the unit with a banner, not kill the whole daily deploy — but a
    stall on OUR side with fresher data upstream is still a hard failure.
    """
    import requests

    try:
        resp = requests.get(
            "https://api.energidataservice.dk/dataset/"
            "ConsumptionDK3619IndustryHour",
            params={"limit": 1, "sort": "TimeUTC DESC"},
            timeout=45,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        if not records:
            return None
        return datetime.fromisoformat(records[0]["TimeUTC"]).replace(tzinfo=UTC)
    except Exception:
        return None  # unknown → keep the strict path


def main(argv: list[str] | None = None) -> int:
    path = Path((sys.argv[1:] if argv is None else argv)[0])
    latest = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    degraded = latest.get("degraded") or []
    stale = find_stale(latest, now)
    hard_stale = []
    source_stalled = []
    for unit, age_h, limit_h in stale:
        snap = latest["units"][unit]
        if snap.get("market") == "DK":
            upstream = source_newest_dk()
            through = datetime.fromisoformat(
                str(snap["data_through"]).replace("Z", "+00:00")
            )
            # source itself hasn't published past what we already have →
            # nothing to fetch: degrade honestly instead of hard-failing
            if upstream is not None and upstream <= through + timedelta(hours=1):
                source_stalled.append((unit, age_h, limit_h, upstream.isoformat()))
                continue
        hard_stale.append((unit, age_h, limit_h))
    if degraded or hard_stale:
        print(
            "HEALTHCHECK FAIL:",
            "degraded:",
            degraded,
            "stale:",
            hard_stale,
            "source-stalled(tolerated):",
            source_stalled,
        )
        return 1
    note = f" source-stalled(tolerated): {source_stalled}" if source_stalled else ""
    print(
        f"HEALTHCHECK OK: {len(latest.get('units', {}))} units,"
        f" issue {latest.get('issue')}.{note}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
