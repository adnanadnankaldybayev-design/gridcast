# GridCast

Open multi-market electricity demand forecasting (Great Britain, Ireland,
Australia/NEM) with a live, self-updating public dashboard and an honest
daily scoreboard of forecast vs. actual.

Status: ** credibility pack landed** — 8 markets ingest + 4-model leak-free
backtest + inverse-MAE ensemble, split-conformal intervals, Diebold–Mariano
reported in two forms (per-point AND conservative per-anchor; "pointwise
only" claims flagged explicitly) + NWP-weather ablation measured. Dashboard
at `site/` + daily CI. Full benchmark card: `reports/BENCHMARK.md` (+
`latest_benchmark.{json,md}` and `latest_nwp_ablation.json`, rebuilt by
`gridcast analyze` / `gridcast ablation nwp`). See `SPEC.md` for the plan.

## Data sources (verified against the live services 2026-09-26/27)

| Market | Source (fixed in code only after a live test) | Access | Cadence |
|---|---|---|---|
| GB | NESO CKAN API `https://api.neso.energy`, dataset `historic-demand-data` → yearly CSV (`demanddataupdate_YYYY.csv`) | open, no key; actuals lag ~21 days | 30 min |
| Ireland (All-Island) | EirGrid Smart Grid Dashboard RSC route `https://www.smartgriddashboard.com/ALL/demand/` with header `RSC: 1` and `?duration=week&datefrom=&dateto=` | open, no key | 15 min |
| Australia (NEM) | AEMO `https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_YYYYMM_{REGION}.csv` (NSW1/QLD1/SA1/TAS1/VIC1) | open, no key | 5 min |
| France | RTE éCO2mix Opendatasoft `https://odre.opendatasoft.com/api/v2/catalog/datasets/eco2mix-national-cons-def/records` (+ rolling `eco2mix-national-tr` for the last ~90 days; the definitive archive refreshes in batches with months of delay) | open, no key | 15 min |
| Germany | SMARD chart API `https://www.smard.de/app/chart_data/410/DE/…` (two-step weekly JSON; values are MWh per 15 min — converted ×4 to MW, pinned by contract test) | open, no key | 15 min |
| Belgium | Elia `https://opendata.elia.be/api/explore/v2.1/catalog/datasets/ods003/records` (eliagridload MW) | open, no key | 15 min |
| Denmark | Energinet EDS `https://api.energidataservice.dk/dataset/ConsumptionDK3619IndustryHour` (national total = sum over DK36 industry codes; BRUTAL 429 limit honored with 'Try again in Ns' + offset paging; settlement lag ~18 days) | open, no key | 60 min |
| Kazakhstan | KOREM `https://portal.korem.kz/api/ct/series?zoneId={1,2}&torgNameId=4` — no key, ~1 req/zone. **Semantics pinned: `demand` is centralized-trades *clearing* demand (~25-45 % of physical consumption), zonal объёмы — NOT physical grid load**; /api/energy/series kept as the physical cross-check. Local dt labels, offset switch UTC+6→UTC+5 on 2024-03-01 handled piecewise | open, no key; attribution: KOREM | 60 min |

Definition caveat (BE): `eliagridload` is *offtake from the Elia transmission
grid* — it excludes distribution-connected load and behind-the-meter solar, so
it runs well below national consumption (series mean ≈ 5.8 GW) and on sunny
spring middays (10–14 UTC) crashes to a few hundred MW (measured min 141 MW,
2026-04-22). The duck-curve shape is verified physical, not a data bug —
but models must expect values near the MAPE floor at solar noon.

Cadence caveat (FR): the definitive éCO2mix export carries `consommation`
only at **30-minute** granularity through 2026-06-30 (odd quarter-hours are
null); the rolling dataset is full 15-min. July 2026 onward coverage is
complete; earlier months are exactly what the operator publishes.

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

## Features and LightGBM (E3)

Feature config is row-per-market (E7-ready): calendar timezones + holiday
specs in `features/calendar.py`, weather points/weights in
`features/weather.py`, publication-safe lag sets in `features/build.py`.

- **Calendar** (`holidays` pkg): GB -> England (Easter Monday!), IE, AU per
  NEM state; local-civil hour-of-day, dow, weekend, morning/evening ramps.
- **Weather** (Open-Meteo Archive, no key, verified live): GB London .45 /
  Manchester .35 / Glasgow .20; IE Dublin; AU one capital per NEM region
  (+NEM consumption-share composite). Temperature, humidity, wind + HDD/CDD
  18 C. Raw JSON snapshots cached (`data/raw/weather/`), backtest runs
  network-free after warmup.
- **Lags — the part everyone gets wrong.** A lag feature is only usable if
  its source is *published* by issue time: `t - lag <= anchor - pub_lag`.
  With GB's 21-day arrears, lag_168h sources are NEVER published at a 48 h
  day-ahead horizon, so lag sets are per-market: GB {672, 840}h, IE/AU
  {168, 336}h. (Measured consequence of getting it wrong: GB GBM hitting
  MAPE 23-25 %, predicting spring levels in August.) LightGBM multistep is
  DIRECT (no recursion; features per horizon point; NaN lags routed by LGBM).
- **Honesty limits**: archive weather ≈ perfect NWP forecast (proxy) → the
  weather value is *bounded* by the ablation below; naive publication lag
  applies equally to all models; GBM refits every 7 anchors (weekly,
  production-style), frozen between refits, lag window refreshed per anchor.

### H1 verdict — naive vs LightGBM (rolling-origin, full archive, 2026-09-26)

| Unit | naive | GBM-weather | GBM-no-weather | Beats naive? |
|---|---|---|---|---|
| GB (MAPE) | 9.72 | **8.35** | 9.81 | **YES (+1.37)** |
| IE (MAPE) | 3.91 | **3.58** | 4.08 | YES (+0.33) |
| AU NSW1 (sMAPE) | 7.01 | **6.77** | 7.69 | YES |
| AU QLD1 (sMAPE) | 5.57 | **4.31** | 5.41 | YES (+1.26) |
| AU SA1 (sMAPE) | 16.27 | **13.33** | 15.09 | YES (+2.93) |
| AU TAS1 (sMAPE) | 7.51 | **6.65** | 7.52 | YES |
| AU VIC1 (sMAPE) | 9.48 | **8.00** | 9.77 | YES |
| AU NEM total (sMAPE) | 4.82 | **4.81** | 5.47 | **YES (+0.01, marginal)** |

Weather ablation value (GBM-weather vs no-weather): −1.45 pts GB, −0.50 IE,
−0.66 NEM, −1.75 SA1 — archive weather is worth real points; a live NWP
forecast will capture most of it (To E5). Note: without weather the GB GBM
(9.81) merely ties naive (9.72) — **calendar+lags alone buy nothing on GB**;
its win comes from weather + recycling lag features properly.

**Where GBM LOSES (honest, from slices/months)**: GB cold-decile days
(naive 8.0 vs GBM 10.2 — GBM over-trusts HDD on cold snaps while the 4-week
lags smooth it); NSW1 & NEM weekends; QLD1 bank holidays (small n); several
early months during model warmup (GB Apr/May, IE Apr, NSW1 Mar-May).
Full by-month / by-horizon / slice tables and cold-day date lists:
`reports/h1_comparison_20260926T190426Z.{json,md}`.

## Model zoo (E4) — 4 models, one protocol, common anchor set

Runner: `gridcast compare` (`--models`, `--chronos-stride`, `--allow-dirty`).
Trust additions (E4a): git-stamped reports with fail-loud provenance, reports
REFUSE a dirty tree without `--allow-dirty`, warmup-flagged anchors with
post-warmup aggregates, compact per-point weather parquet cache (1715 legacy
snapshots migrated to 9 files), cold-slice thresholds from 1-year-back
climatology (never the measured window), Chronos anchor stride = 6
(rotates weekdays; slice-complete), cross-model metrics on the COMMON
anchor intersection.

Chronos-Bolt-mini runs ZERO-SHOT on CPU (`models/chronos.py`; install via
`.[chronos]`); fit() is a context cut by design; `torch` heavy deps are
optional extras.

### Measured on the full archive (common anchor set; 2026-09-26, SHA d7d698b+)

| Unit | naive | ridge-w | GBM-w | chronos-0shot | Best |
|---|---|---|---|---|---|
| GB (MAPE) | 9.49 | 11.77 | **8.66** | 8.98 | GBM |
| IE (MAPE) | 3.76 | 3.81 | **3.33** | 14.26 | GBM |
| AU NSW1 (sMAPE) | 7.16 | 6.69 | **6.52** | 20.63 | GBM |
| AU QLD1 (sMAPE) | 5.62 | 5.03 | **3.91** | 22.87 | GBM |
| AU SA1 (sMAPE) | 17.18 | 16.76 | **14.44** | 34.10 | GBM |
| AU TAS1 (sMAPE) | 7.81 | **6.15** | 6.36 | 14.63 | ridge |
| AU VIC1 (sMAPE) | 10.09 | **7.57** | 8.08 | 21.87 | ridge |
| AU NEM total (sMAPE) | 4.95 | **4.48** | 4.76 | 20.92 | ridge |

**Findings (honest):**
- H1 (GBM beats naive): **8/8 units, re-confirmed on a second anchor set**,
  margins −0.2…−2.7 pts; but ridge wins on TAS1/VIC1/NEM — Australia is
  strongly thermal-linear; the honest floor is non-trivial.
- H2 (zero-shot chronos-bolt-mini): **fails at fine cadences and long AR
  horizons** (IE 15-min: 14.3 MAPE; AU 5-min sMAPE 14.6–34.1 — model simply
    cannot AR-extend 192–576 steps well). BUT on GB (30-min, 3 weeks public
  arrears for every one) zero-shot **beats naive 8.98 vs 9.49** and is the
  best on the anomalous slices, measured on the common anchor set:
  **cold-decile 9.16 vs 9.84 naive / 15.29 GBM**, weekends 11.63 vs 13.01
  naive. Bank holidays are NOT a Chronos win: GBM leads 8.10 vs 11.29
  (only 2 holiday anchors in the common set — thin evidence either way).
  That is exactly the H2 claim — limited by cadence and publication
  latency, not by domain shift alone.
- Ridge's GB failure (11.77) vs GBM (8.66) shows nonlinearity matters where
  features are few (lags ≥ 4 weeks); Australia's richer same-week lags let
  linear win on three units.
- chronos-GB by-month (common anchors): wins in 2026-04 (16.15 vs 19.98
  naive) and 2026-05 (6.32 vs 8.57), Jun-Aug loses — evidence for further
  study is real but narrow; E5 should try hourly resampled Chronos for
  IE/AU and bolt-small once RAM allows.

Artifacts: `reports/model_zoo_20260926T204652Z.{json,md}` (by-month,
by-horizon, slices — all on the common anchor intersection — climatological
cold-day lists, warmup/post-warmup). The earlier `...203017Z` artifacts
predate the common-anchor slice fix (G3 review) and are kept for the audit
trail; their slice/bank-holiday numbers are superseded.

### For E3/E5 (recorded during E2): GB operator forecast source

NESO dataset `1-day-ahead-demand-forecast` (live-verified 2026-09-26):
daily file `ng_demand_1da_YYYYMMDD.csv` (tomorrow's forecast, for the live
dashboard) and `archive_1dayahead.csv` (back to 2018) — but the archive is in
compressed *cardinal-points* form (11 characteristic points per day with
minute offsets + `FORECAST_TIMESTAMP` vintage), not half-hourly. Expanding it
into a comparable series is E3 work for hypothesis H3, not a quick E1 add-on.

## License

MIT — see `LICENSE`.
