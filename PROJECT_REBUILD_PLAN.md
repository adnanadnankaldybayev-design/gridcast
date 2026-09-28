# PROJECT_REBUILD_PLAN.md — аудит-база перестройки презентационного слоя

Дата аудита: 2026-09-28. База кода: HEAD `227a32f` (после фикса теста wall-clock).
Аудитор: G3-группа (Data Quality + Security + Adversarial + University Reviewer),
серия из 8 враждебных ревью до этого (utechek hunt, математика руками,
воспроизводимость бит-в-бит). Метод: команды и логи, не впечатления.

Резюме одной строкой: **бэкенд-ядро (данные → протокол оценки → модели →
trust-слой → daily-раннер) — консервируем; презентационный слой (site/, визуал
README, нарратив для пользователя) — в полную перестройку.**

---

## 1. КОНСЕРВИРУЕМ (тащить в новую версию как есть — мотивы)

### 1.1 Данные и инжест (`src/gridcast/ingest/`, `data/`)
- 9 адаптеров операторов (NESO, EirGrid, AEMO, Elia, SMARD, Energinet, RTE,
  KOREM×2 зоны) + `base.py` (ретраи, raw-снапшоты, merge-на-инкремент,
  атомарные партиции). Три раунда враждебных ревью; единицы и TZ сверены
  независимо сырыми ответами (SMARD ×4 по цифре, KZ label→UTC точное совпадение
  значения, DST-сетки всех рынков на parquet).
- Byte-pinned контрактные фикстуры (`tests/fixtures/`) — реальные вырезки
  ответов, а не синтетика; `.gitattributes` фиксирует EOL.
- Raw-снапшоты: доказали свою ценность минимум дважды (ревизия SMARD,
  смена домена NESO). Не трогать.

### 1.2 Протокол оценки (`src/gridcast/eval/`)
- rolling-origin с publication-lag катоффами по каждому оператору
  (`PUB_LAG_DAYS`), warmup-флаг + post-warmup агрегаты, stride-якоря,
  common-anchor intersection для всех кросс-модельных таблиц. Утечки искались
  в 4 захода, включая отравление будущего со сломанным cutoff.
- Метрики (MAE/MAPE/sMAPE/б floor) — пересчитаны руками, не библиотекой.
- Split-conformal (rolling 14 якорей) — poison-future эксперимент: ранние
  интервалы байт-в-байт неизменны.
- Diebold–Mariano с Newey–West — HAC сверен с ручным расчётом до 1e-12.
- Ensemble inverse-MAE — веса только из прошлых якорей (spy-тест + dedupe
  hot-path после 653fe08).
- `MARKET_LAG_HOURS` с инвариант-тестом (поймал DK) — публикационная
  безопасность лагов теперь гарантирована тестом, а не инспекцией.

### 1.3 Модели (`src/gridcast/models/`)
- naive (fallback-лестница), ridge (pipeline, скейлер только на train),
  GBM (random_state=42 + deterministic=True — бит-воспроизводимость),
  Chronos zero-shot (fit = контекст-кат, ничего не тренирует).
  Протокол ForecastModel — единая точка расширения.

### 1.4 Trust-слой
- provenance fail-loud (`git_state`), clean-tree guard CLI (`--allow-dirty`),
  latest_*-ретенция reports, healthcheck per-market (после фикса 1dec26a),
  запрет timestamped-артефактов в git.

### 1.5 Daily-раннер (`src/gridcast/publish/forecast.py`, `healthcheck.py`)
- Leak-guard тест доказан сенситивным (сломанный cutoff → прогноз меняется).
- graceful degrade + merge со вчерашним, healthcheck per-market staleness.

### 1.6 Контракт данных фронта — `site/data/*.json` (НЕ ЛОМАТЬ)
- `latest_forecasts.json`: `{generated_at, issue, horizon_h, units{}, degraded[]}`;
  unit: `{issue, market, unit, champion, weights, data_through, horizon_h,
  n_fit_points, published_demand_tail[{t,v}], points[{t,pred,lo80,hi80,lo90,hi90}]}`.
- `forecast_history.json`: `{days[{date, units{u:{champion, data_through,
  horizon_mean_mw, points_short[...]}}}]}` (rolling 60 дней).
- `metrics.json`: `{generated_at, units{u:{champion_model, primary_metric,
  champion_value, naive_value}}}`.
- Эти файлы бот-коммитит daily.yml; их схему расширяем (новые поля) только
  через publish-слой, существующие поля не переименовываем.

### 1.7 Тесты, CI-workflows, зависимости
- 105 тестов (после фикса 227a32f); ci.yml + daily.yml (кэш данных, инкремент-
  инжест, бот-коммиты, deploy-pages) после 1740036/653fe08.
- `pyproject` deps: pandas/pyarrow/requests/holidays/tzdata/lightgbm/sklearn
  + optional chronos. Torch остаётся optional (CI без него).

## 2. РЕМОНТ (по приоритету; ничего блокирующего после аудита)

### P1 — научная строгость и long-tail качества
1. **DM per-anchor вариант** (`eval/dm.py`): сейчас d_t по точкам (n=2112,
   overlap ~47h между соседними якорями). Добавить агрегацию mean|e| per anchor
   (n=22–30) как строгий вариант рядом; обновить BENCHMARK limitations,
   если выводы меняются. Первый вопрос любого профессора — именно сюда.
2. **Conformal под аномалии**: TAS1 cold P80 0.45 — задокументировано, но
   research-трек должен попробовать horizon-условные интервалы
   (квантили отдельно по 0–24h / 24–48h) и/или пер-календарные (holiday/cold)
   калибровки. Метрики успеха — PICP по срезам в диапазон 0.75–0.85.
3. **Archive-vs-NWP зазор измерить числом**: один экспериментальный прогон
   `gridcast backtest --model gbm` где predict-погода = NWP-архив прогнозов
   (Open-Meteo forecast archive), вместо reanalysis; в BENCHMARK записать
   дельту как живое доказательство по абляции.
4. **Инкрементальный forecast**: после dedupe (653fe08) ensemble-юниты всё ещё
   ~20+ фитов GBM на юнит; добавить кэш residual-анкоров между днями (веса
   обновляются только за новый день). Цель: п.3 из секции рисков ниже.
5. **`anchors_for` end-семантика** (`eval/backtest.py:88`): end трактуется как
   полуночная граница — задокументировать явно в docstring/CLI-help
   (дешевле правки поведения, совместимости не ломает).
6. **CRLF-файл** `src/gridcast/features/weather.py`: нормализовать через один
   отдельный коммит (`dos2unix`), чтобы дифы больше не тащили `\r`.

### P2 — гигиена
7. `deploy-pages@v4` без параметра `url` (warning-suppression) + добавить
   `environment: github-pages` в daily.yml (deploy-URL становится виден в
   Actions UI + защита env-секретов).
8. `analyze` CLI: флаг `--units` (есть параметр у `run_analysis`, нет в CLI).
9. `gridcast backtest/compare/analyze/forecast`: одинаковая обработка
   `ValueError` ("no anchors") → exit 2 с сообщением (часть уже есть).
10. **metrics.json v2**: добавить per-unit `caveat`/`display_name`/`unit_tz`/
    `mape_floor_note` (BE-ум, KZ-семантика, GB/ DK-лаг), которые UI рендерит
    из ДАННЫХ, а не хардкода в JS. См. секцию 3 — это подготовка контракта.
11. `latest_forecasts.json` v2 (backward-compatible): `units_meta{u:
    {display_name, market_tz, cadence_min, pub_lag_days, caveat_text}}` —
    источник истины для страны-эксплореров нового сайта.
12. SMARD-ревизии: политика — периодический re-pull последних 2 недель или
    зафиксировать "значение = редакция на дату снапшота" в README.

## 3. ПЕРЕПИСЫВАЕМ — site/ полностью (цель: "premium research/data platform")

### 3.1 Пять главных требований (недоговороспособные)
1. **Contract-first**: UI читает только `site/data/*.json` + metadata-поля
   из P2.10/2.11. Никаких значений/кейватов/имён рынков в JS-константах —
   они приходят данными. Критерий приёмки: смена текста кейвата в publish-слое
   меняет сайт без правки фронта.
2. **Trust as design**: provenance виден на каждом экране: generated_at,
   git SHA (добавить в metrics.json через finish_report), data_through с
   подписью "actuals lag — норма издателя", degrade/stale — designed states
   (card-level), не алерт на весь экран.
3. **Purpose per screen** (5 экранов):
   - **Landing** (`/`): что это, почему честный бенчмарк, 3 ключевых числа,
     живой график-герой одного рынка, CTA в dashboard; 8 рынков плиткой.
   - **Dashboard** (`/dashboard.html`): "вчера сказали — сегодня факт":
     последний прогноз vs опубликованный факт по всем юнитам; leaderboard
     по primary-метрике; degrade-состояния.
   - **Country explorer** (`/markets/{unit}.html` или SPA-панели): карточка
     рынка — профиль данных (вердикты §5 этого документа), кейваты рынка,
     исторический график, локальная TZ, источник со ссылкой.
   - **Forecast explorer** (`/forecast.html`): выбранный юнит — прогноз 48h,
     интервалы 80/90, overlay вчерашних прогнозов (как сейчас concept),
     разбивка ошибки по горизонтам из latest_benchmark (by_horizon).
   - **Methodology** (`/methodology.html`): протокол, publication lags,
     таблица моделей, limitations со ссылками на BENCHMARK.md/JSON.
4. **Micro-details обязательны**: skeleton-загрузки на каждый fetch, error
   state с retry, empty state "данных нет — следующий daily прогон";
   числа/даты/единицы отформатированы (GW/MW автоподбор, Intl, локальные TZ
   подписи); transitions без layout shift; hover/focus на интерактивах;
   клавиатурная навигация; `prefers-reduced-motion`; noscript с ссылкой на
   статический скриншот и JSON.
5. **Zero-build static + budget**: чистые HTML/CSS/JS (или один pinned
   chart-бандл с SRI; при невозможности SRI — вендорим локально в
   `site/vendor/`); без runtime secrets; Lighthouse ≥ 95 perf + ≥ 100 a11y
   на desktop и mobile; изображения весом бюджетом ≤ 300KB/страницу на старте.

### 3.2 Что переиспользуем из текущего UI
- Концепции: validation-overlay (вчерашний прогноз поверх факта),
  degrade-баннер, тёмная палитра как основа токенов.
- `site/data/*.json` (контракт), статический деплой через Pages.

### 3.3 Что точно переписываем (диагноз текущего сайта)
- Одна карточка на всё: picker-кнопки без метрик, MPL-стиль таблиц,
  отсутствие information hierarchy; `fmt = Intl.NumberFormat(...)` объявлен
  и не используется (мёртвый код в app.js) — симптом сырости.
- Нет skeleton/error/empty состояний (один textContent "Loading…").
- Даты сырые ISO в аннотациях; числа не форматированы; MW везде (GB лучше GW).
- Plotly CDN без SRI; min-height 460px не адаптивен; нет prefers-reduced-motion;
  focus states отсутствуют; footer-тон «high-schooler» — заменить нейтральным.

## 4. ДОБАВЛЯЕМ
1. **README до профессионального**: architecture diagram (ASCII или
   generated SVG в docs/), скриншоты новых экранов (после R2–R4), badges
   (CI passing / license / tests), live demo URL, quickstart в 3 команды,
   ссылка на BENCHMARK.md как model card.
2. **docs/visuals**: диаграмма пайплайна (ingest→eval→publish→site),
   график "forecast vs last-week actuals" PNG для лендинга/README,
   таблица покрытия рынков (из §5).
3. **Provenance в данных**: metrics.json + `generated_by.git_sha`
   (малая правка `_write_metrics`).

## 5. УДАЛЯЕМ
1. `notebooks/chronos_smoke.py`, `chronos_smoke2.py`, `debug_cold.py` —
   разведочные скрипты (ruff-excluded); знания уже в тестах/BENCHMARK.
   Если ностальгия — перенести в `docs/dev-notes/` как markdown-заметку.
2. `ROADMAP-V2.md` — superseded этим планом: заменить содержимое ссылкой
   на PROJECT_REBUILD_PLAN.md (не удалять git-history).
3. Мёртвого кода в src/ скан не нашёл (grep TODO/FIXME чист, fr_rte
   fetch_day/parse_records живут для контрактных тестов — оставляем).

## 6. Данные: вердикты по юнитам (снимок parquet на дату аудита)

| Юнит | Покрытие | Риски | Вердикт |
|---|---|---|---|
| GB/GB | 03-01 → 09-05, 0% дыр, MW 12.6–38.2 ГВт | 21д лаг — норма издателя | доверяю |
| IE/ALL | → 09-26, holes 0.08% (upstream nulls) | нет | доверяю |
| AU NSW1/QLD1/VIC1/TAS1 | → 09-26, 0% дыр | нет | доверяю |
| AU SA1 | → 09-26, min −225 MW | sMAPE-only себе; MAPE floor исключает 0.83% | доверяю с оговоркой |
| FR/FR | → 09-27, null 29.1% (Mar–Jun = 30-мин definitive, ровно 50% null в каждом месяце) | смешанная каденция — фичи/метрики помнят | с оговоркой |
| DE/DE | → 09-27, null 0.3% | SMARD ревизует задним числом (политика P2.12) | доверяю |
| BE/BE | → 09-26, mean 5.8 ГВт, min 141 MW | Elia-offtake ≠ нац. нагрузка; MAPE floor близко на солнечном полудне | с оговоркой |
| DK/DK | → 09-08, hourly | settlement lag 18д — норма; лаги моделей теперь 504/672 | доверяю |
| KZ/KZ, KZ_W | → 09-27, hourly | клиринговый спрос ЦТ ~25–45% физики; KZ_W min 60.6 MW (0.12% точек < floor) | с оговоркой |

## 7. ML: что уже честно задокументировано vs что чинить Research-треку

Уже честно (BENCHMARK.md limitations + undercoverage-таблицы + slices):
- DM-оговорка про overlapping horizons; хронos на мелкой каденции; TAS1-cold
  провалы conformal; warmup; archive-weather proxy; BE floor; H2 partial.

Чинить Research-треком (п.1–3 секции РЕМОНТ): DM per-anchor вариант,
conformal под аномалии, NWP-дельта числом, IE/GB ensemble-веса эволюция
(вес chronos в daily runner отсутствует по дизайну — в weekly analyze есть).

## 8. План по этапам (каждый = shipped-инкремент, G3-ревью между)

- **R0 Contract v2 (backend, 1 день)**: `metrics.json` + caveat/display_meta,
  `latest_forecasts.json` + units_meta, `generated_by.git_sha`; schema-тесты
  расширены. DoD: pytest зелёный; старые ключи неизменны (diff-assert);
  один прогон `gridcast forecast` выдаёт v2 без падения.
- **R1 Design system + landing (2–3 дня)**: токены (цвет/типографика/spacing),
  landing со story+3 числами+плитка рынков; skeleton+noscript.
  DoD: Lighthouse ≥95/≥100 a11y; WCAG AA проверка контрастов; mobile 360px.
- **R2 Dashboard-экран (2 дня)**: прогноз-vs-факт по всем юнитам, leaderboard,
  degrade card-level, provenance-badges (SHA, generated_at, data_through).
  DoD: на посаженном nested degrade/stale рендерятся designed states;
  форматирование единиц GW/MW по правилу; +visual snapshot-тест.
- **R3 Country + Forecast explorers (3 дня)**: карточки 8 рынков из metadata,
  by-horizon разложение ошибки, interval-графики, overlay-вчера.
  DoD: каждый кейват из metrics.json виден; per-horizon bar/small-multiples.
- **R4 Methodology (1 день)**: протокол, модели, limitations, ссылки на
  артефакты; diagram из п.4.2. DoD: ссылки на GitHub-файлы резолвятся.
- **R5 README-визуалы + деплой-проверка (1 день)**: скриншоты, badges,
  diagram, demo URL; ручная проверка production URL после daily-рана (G4).
- **R6 Director-гейт** (по AGENTS v2 чек-листу из 14 пунктов).

## 9. Риски и правила безопасности перестройки
- **Параллельная работа**: в дереве сейчас есть незакоммиченные правки site/ от
  frontend-агента — правила координации: backend-агенты не коммитят в site/
  до конца R2; коммиты точечно по файлам (никакого `git add -A`).
- **Бот-коммиты**: новый UI продолжает писать данные только в `site/data/`;
  если появится build-шаг, его выход тоже в `site/data/` или отдельный dist/
  с обновлением daily.yml commit-path (R5).
- **Непрерывность дашборда**: пока site/ переписывается, daily.yml должен
  продолжать работать — любая правка workflow отдельным коммитом с ясным
  намерением; `latest_forecasts.json` обратная совместимость в R0 не нарушается.
- **Запрет**: не «улучшать» src/eval/models ради UI; не хардкодить рынки/метрики
  в JS; не удалять `.gitkeep` в reports/data; не трогать тест-фикстуры
  (byte-контракты).
