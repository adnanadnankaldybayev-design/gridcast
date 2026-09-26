# SPEC — GridCast (проект 01)

**GridCast — open multi-market electricity demand forecasting with a live,
self-updating public dashboard.**
Статус: G1 (спека утверждена Director'ом, готово к сборке). Дата: 2026-09-26.

## 1. Проблема и оригинальность

Системные операторы публикуют факт спроса на электроэнергию и собственный
краткосрочный прогноз, но независимой открытой системы, которая ежедневно
прогнозирует спрос на нескольких рынках сразу, показывает свою ошибку против
факта и честно сравнивает классический ML с zero-shot foundation-моделью
време́нных рядов, нет. Учебные проекты по energy-forecasting — однорыночные
(PJM/UK) и без живого артефакта.

Что строим: систему, которая **каждый день автоматически** (GitHub Actions):
забирает свежий факт спроса по рынкам GB / Ireland / Australia, строит прогноз
на завтра двумя моделями, публикует на статическом сайте (GitHub Pages) графики
«прогноз vs факт vs прогноз оператора» и таблицу метрик. Плюс воспроизводимый
backtest на историческом архиве (rolling-origin, без утечек) и публичный
очищенный датасет.

## 2. Гипотезы (проверяемые)

- H1: LightGBM (календарь, погода, лаги) бьёт сезонно-наивный baseline и
  zero-shot Chronos-Bolt в среднем по горизонту 24–48 ч на каждом рынке.
- H2: zero-shot Chronos конкурентен в редко встречающиеся дни (bank holidays,
  холодные волны), где у GBM мало обучающих примеров — проверить срезами.
- H3: ошибка нашей модели сопоставима с ошибкой операторского прогноза
  (внешний ориентир качества) минимум на 2 из 3 рынков.
- H4 (мультирынок): перенос фичей/признаковой схемы между рынками сохраняет ≥90%
  качества относительно per-market тюнинга — аргумент масштабируемости системы.

## 3. Данные (всё открытое, без платных ключей; эндпоинты верифицируются в E1)

- **GB**: NESO open data portal (data.neso.energy, CKAN API) — получасовой
  исторический спрос + операторский day-ahead прогноз.
- **Ireland (IE)**: EirGrid Smart Grid Dashboard API — факт спроса (15-мин) и
  прогнозы.
- **Australia (AU)**: AEMO NEMWEB — 5-мин/30-мин спрос, публичные архивы CSV.
- **Погода**: Open-Meteo Archive + Forecast API (бесплатно, без ключа) — температура
  взвешенная по населению для каждого рынка.
- **Календарь**: пакет `holidays` (GB/IE/AU bank holidays) + ручной слой
  исключений.
- С первого дня — ежедневные сырые снапшоты ответов в `data/raw/` (источники
  меняют форматы; сырьё храним неизменным).

## 4. Архитектура

```
NESO / EirGrid / AEMO ─┐
Open-Meteo             ┼─► ingest (Python, per-source adapters) ─► data/processed/ (Parquet)
holidays               ┘                                            │
                              features/ (calendar, lags, weather)   ▼
                              models/ (naive, LightGBM, Chronos zero-shot)
                              eval/ (rolling-origin backtest → metrics JSON)
                              site/ (static + Plotly.js, generated from data)
GitHub Actions: daily.yml (ingest → predict → publish), ci.yml (ruff + pytest)
```

Стек: Python 3.12+, pandas/polars, LightGBM, chronos-forecasting (CPU),
Plotly.js, GitHub Pages. Без Docker, без платных API, без БД-сервера.

## 5. Структура репозитория

```
gridcast/
├── README.md  LICENSE  pyproject.toml  .github/workflows/
├── src/gridcast/ (ingest/, features/, models/, eval/, publish/)
├── tests/        data/ (raw/, processed/)  notebooks/ (исследование)
├── site/ (index.html + assets, генерируется)
└── reports/ (метрики по дням/рынкам, changelog модели)
```

## 6. Критерии успеха (Definition of Done проекта)

1. Дашборд на GitHub Pages обновляется ежедневно ≥ 30 дней подряд без ручного
   вмешательства, по ≥ 2 рынкам.
2. Backtest: MAPE LightGBM < MAPE seasonal-naive и < ошибки операторского
   прогноза на скользящем окне ≥ 90 дней; воспроизводимо `make backtest`.
3. Срезы по типам дней (weekday/weekend/bank holiday/heat/cold) с честными
   выводами, включая где модель проигрывает.
4. Публичный очищенный датасет + скрипты сборки (до-воспроизводимо).
5. README: what/why/how, архитектура, метрики, limitations, скриншоты, live URL.
6. Конкурсный пакет (GENIUS/общий): аннотация EN, 2-мин demo video, постер-структура.

## 7. Этапы (каждый — гейт G2→G3, отдельный блок работы)

- **E0 Setup**: Python 3.12+, репозиторий, CI-скелет (ruff+pytest), git identity.
- **E1 Data**: верификация эндпоинтов NESO/EirGrid/AEMO (первой задачей!),
  per-source адаптеры, контракт-тесты форматов, ≥6 мес архива в Parquet.
  DoD: `gridcast ingest --all` зелёное, тесты зелёные.
- **E2 Baseline + backtest-движок**: seasonal-naive, rolling-origin, метрики JSON.
- **E3 GBM + фичи**: календарь, погода, лаги; проверка H1.
- **E4 Chronos zero-shot**: CPU-инференс на backtest; H2, срезы; H4-перенос.
- **E5 Live-дашборд**: daily workflow, сайт на Pages, прогноз-на-завтра по
  рынкам, healthcheck-алерт при сбое инжеста, graceful degrade.
- **E6 Упаковка**: README pro, LICENSE, demo video, конкурсные материалы,
  финальный G3-аудит «глазами сильного инженера».

## 8. Риски и митигации

- Форматы операторских API меняются → контрактные тесты + сырые снапшоты +
  дашборд показывает последнюю валидную дату + баннер.
- Какой-то рынок окажется недоступен без ключа → архитектура per-source
  адаптеров, система живёт на оставшихся (минимум GB).
- Лимиты GitHub Actions (CPU/время) → daily-прогноз на GBM; Chronos — только в
  недельном backtest-раннере; кэш pip.
- История API короткая → для backtest-разогрева брать публикуемые архивы
  операторов с первой недели.
- «Спринт под дедлайн» читается в портфолио → начинаем немедленно, дуга коммитов ≥ 3 мес.

## 9. Out of scope

Реал-тайм (минутные) прогнозы в продукте; прогноз цен; почасовые +
внутричасовые регионы помимо трёх рынков; обучение собственной
foundation-модели; мобильное приложение.
