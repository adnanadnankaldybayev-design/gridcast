# GridCast

Open multi-market electricity demand forecasting (Great Britain, Ireland,
Australia/NEM) with a live, self-updating public dashboard and an honest
daily scoreboard of forecast vs. actual.

Status: **E1 done (data ingestion live)**, E2 (baseline + backtest) next.
See `SPEC.md` for the full plan.

## Data sources (verified against the live services 2026-09-26)

| Market | Source (fixed in code only after a live test) | Access | Cadence |
|---|---|---|---|
| GB | NESO CKAN API `https://api.neso.energy`, dataset `historic-demand-data` → yearly CSV (`demanddataupdate_YYYY.csv`) | open, no key; actuals lag ~21 days | 30 min |
| Ireland (All-Island) | EirGrid Smart Grid Dashboard RSC route `https://www.smartgriddashboard.com/ALL/demand/` with header `RSC: 1` and `?duration=week&datefrom=&dateto=` | open, no key | 15 min |
| Australia (NEM) | AEMO `https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_YYYYMM_{REGION}.csv` (NSW1/QLD1/SA1/TAS1/VIC1) | open, no key | 5 min |

Hard-won facts encoded in the adapters (all verified on real responses):

- `data.neso.energy` and `data.nationalgrideso.com` no longer resolve; the
  portal lives at `api.neso.energy`. Yearly CSV files differ across years:
  2025 and older are quoted and actuals-only, 2026+ add a
  `FORECAST_ACTUAL_INDICATOR` ('F' = provisional) column.
- GB settlement periods are elapsed 30-min blocks from local midnight:
  spring-forward days have 46, fall-back days 50 periods (verified on
  2026-03-29 / 2025-10-26). Conversion: local midnight→UTC + (SP−1)×30 min.
- The EirGrid legacy `/Dashboard/Svc` JSON-RPC is gone (404); its successor
  `/DashboardService.svc/csv` throttles to HTTP 503 after a couple of
  requests. The RSC route (used by the live dashboard itself) serves week
  windows back to 2019; timestamps sit on a full 24h grid on DST-change days,
  i.e. they are UTC. Roughly 1 in ~30 requests returns a payload without the
  series (transient) — the adapter retries and skips with an error log.
- NEM market time is fixed UTC+10 (no DST). SA1 operational demand is
  negative at solar noon (88 intervals in March 2026 alone, min −224.6 MW) —
  a real DER effect, kept as-is, not an error.

### First full pull (`python -m gridcast.ingest --all --start 2026-03-01`)

| Market | Rows | First (UTC) | Last (UTC) | Grid gaps |
|---|---|---|---|---|
| GB | 9 070 | 2026-03-01 00:00 | 2026-09-05 22:30 | 0.0 % |
| IE | 20 143 | 2026-03-01 00:00 | 2026-09-26 17:30 | 0.02 % |
| AU | 301 805 | 2026-03-01 00:00 | 2026-09-26 14:00 | 0.0 % per region |

IE coverage is 96/96 intervals for every historical day except 2026-03-29
(92/96 — 4 measurements null upstream); intraday "today" is partial by
definition, and its future slots carry the operator's forecast demand.
GB's series ends ~21 days before today on any given run — the publisher's
own 21-day arrears, not missing data.

## Layout

```
src/gridcast/
  ingest/    per-source adapters (neso.py, eirgrid.py, aemo.py) -> Parquet
  features/  (E3) calendar / weather / lags
  models/    (E2+) naive, LightGBM, Chronos zero-shot
  eval/      (E2) rolling-origin backtest -> metrics JSON
  publish/   (E5) static dashboard generation
tests/       contract tests on real-response fixtures (tests/fixtures/)
data/        raw/ immutable snapshots + processed/ parquet (gitignored)
notebooks/ site/ reports/
```

## Quickstart

```bash
make setup          # python -m venv .venv && pip install -e ".[dev]"
make lint           # ruff check .
make test           # pytest (offline: contract tests on saved fixtures)
make ingest         # python -m gridcast.ingest --all  (six-month lookback)
```

Windows without make: same commands via `.venv/Scripts/python` (e.g.
`.venv/Scripts/python -m pytest`). A console script `gridcast` is installed
into the venv as well (`gridcast ingest --all`).

Raw responses are snapshotted byte-for-byte under `data/raw/<source>/` on
every run, and processed data lands in monthly Parquet partitions
`data/processed/demand_{MARKET}_{YYYY-MM}.parquet` (rewritten idempotently).

Normalized schema: `timestamp (UTC)`, `market`, `region`, `demand_mw`,
`forecast_mw` (operator forecast where available), `source`.

## License

MIT — see `LICENSE`.
