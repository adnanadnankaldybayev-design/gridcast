# GridCast

Open multi-market electricity demand forecasting (Great Britain, Ireland,
Australia/NEM) with a live, self-updating public dashboard and an honest
daily scoreboard of forecast vs. actual.

Status: **E2 done** (ingestion + leak-free backtest engine + seasonal-naive
baseline with real measured numbers), E3 (GBM + features) next.
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

## Backtest (E2)

```
python -m gridcast.cli backtest            # or: .venv/Scripts/gridcast backtest
# options: --market GB IE AU --start/--end YYYY-MM-DD --step-hours 24
#          --horizon-hours 48 --train-days N (default: expanding) --issue-hour 12
```

Protocol (mirrors the future live daily job, verified by tests):

- daily anchors at `issue_hour_utc`; the model is fit ONLY on data published
  by `anchor - pub_lag` (GB: 21 days — NESO's own arrears; IE/AU: 6 h),
  then predicts the full 48 h horizon at the market's native cadence;
- leakage is tested, not assumed: a spy model proves fit windows never cross
  the publication cutoff, and a run with the future overwritten by garbage
  must produce byte-identical predictions (`tests/test_backtest_engine.py`);
- every model implements `fit(history) / predict(timestamps)`
  (`src/gridcast/models/base.py`) so LightGBM/Chronos plug in unchanged.

Metrics: MAE (MW), sMAPE and MAPE. MAPE excludes points with
`|actual| < 100 MW` and reports the excluded share — SA1 operational demand
crosses zero at solar noon, so for AU the ratio metric of record is **sMAPE**;
GB/IE keep MAPE. Reports land in `reports/backtest_<model>_<ts>.json` with
git SHA + generation timestamp, aggregated overall / per horizon step / per
month (AU: per region and NEM total).

### Seasonal-naive (168 h) on the full E1 archive — measured 2026-09-26

Run: `gridcast backtest` (anchors 2026-03-01..2026-09-26, 48 h horizon,
expanding window; GB anchors start 2026-03-22 because of the 21-day lag).

| Unit | Primary metric | MAE (MW) | Anchors |
|---|---|---|---|
| GB | MAPE **11.12 %** | 2 440.5 | 166 |
| IE (All-Island) | MAPE **4.21 %** | 201.5 | 207 |
| AU NSW1 | sMAPE 7.74 % | 572.4 | 207 |
| AU QLD1 | sMAPE 5.91 % | 331.1 | 207 |
| AU SA1 | sMAPE 19.02 % | 190.9 | 207 |
| AU TAS1 | sMAPE 7.40 % | 79.3 | 207 |
| AU VIC1 | sMAPE 9.74 % | 506.6 | 207 |
| AU NEM total | sMAPE **5.18 %** | 1 075.6 | 207 |

Interpretation: the GB number is deliberately conservative — with a 21-day
publication lag the naive model can only use "same slot 4 weeks ago", so its
error tracks the intraday shape (≈18 % during ramps, ≈7 % midday). Any model
that beats it must do so under the same honesty constraint. SA1's 19 % sMAPE
confirms midday solar volatility as the hardest forecasting case in the data.

### For E3/E5 (recorded during E2): GB operator forecast source

NESO dataset `1-day-ahead-demand-forecast` (live-verified 2026-09-26):
daily file `ng_demand_1da_YYYYMMDD.csv` (tomorrow's forecast, for the live
dashboard) and `archive_1dayahead.csv` (back to 2018) — but the archive is in
compressed *cardinal-points* form (11 characteristic points per day with
minute offsets + `FORECAST_TIMESTAMP` vintage), not half-hourly. Expanding it
into a comparable series is E3 work for hypothesis H3, not a quick E1 add-on.

## License

MIT — see `LICENSE`.
