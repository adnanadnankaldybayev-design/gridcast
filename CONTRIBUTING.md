# Contributing to GridCast

Thanks for looking. GridCast is a research-grade benchmark, so the bar for
"works on my machine" is higher than usual — this file is the whole contract.

## Setup

```bash
make setup          # python -m venv .venv && pip install -e ".[dev]"
make lint           # ruff check .
make test           # pytest (offline; must stay offline)
npm ci && npm run smoke   # jsdom execution smoke over the 5 site pages
```

Windows without make: run the same commands via `.venv/Scripts/python`.

## The gates (all must pass before any commit)

1. `ruff check .` — clean.
2. Full `pytest` — clean, and **offline**: tests must never hit the live
   network. Forecast/model tests seed weather via
   `gridcast.features.weather.seed_point_data` (RAW column names —
   `temperature_2m`, not `w_temperature_2m`; the module adds the prefix).
   New heavy/flaky behavior without a stub is a defect, not a detail.
3. `npm run smoke` — passes on all 5 pages.

## Project invariants you must not break

- **Publication discipline.** No feature/prediction may use data newer than
  `anchor - PUB_LAG_DAYS[market]`. Lag sets per market live in
  `features/build.py` and are protected by an invariant test
  (`min(lag) >= pub_lag*24 + 48h`). If you add a market, add the invariant
  entry with it.
- **Provenance.** Anything written under `reports/` or `site/data/` carries
  git sha + dirty flag. Unstamped artifacts are a bug. Report-generating
  CLIs refuse dirty trees (pass `--allow-dirty` only for experiments that
  must not become evidence).
- **Contract v2.** `site/data/*.json` is additive-only: new keys welcome,
  renamed/removed keys are a breaking change for the deployed site.
- **Snapshots.** `data/raw/` byte-level snapshots are append-only and
  gitignored; never edit historical fixtures in `tests/fixtures/`
  (byte-pinned contracts of upstream formats).
- **Honesty in numbers.** Every number shown in README/site/cards must be
  traceable to a run in this repo. If a number is a modeling choice, say so.

## Conventions

- Conventional commits: `feat|fix|docs|test|chore|perf(scope): ...`.
- Python style: whatever `ruff` enforces (line length 100).
- Comments explain why a non-obvious constraint exists, not what the line does.
- Weather/weather-forecast global memos in `features/weather.py` are
  process-global: test fixtures re-seed explicitly per unit.

## Good first issues

- CONF-metric coverage gaps on `daily.yml` (any new page or JSON must get a
  smoke assert in `scripts/site-smoke.mjs`).
- A market adapter you can verify against a live operator endpoint —
  fixture first (real response), parser second, contract test third.
