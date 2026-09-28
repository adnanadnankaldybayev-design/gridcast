/* Landing — hero chart of the default market (ranked by units_meta order),
 * KPI tiles, trust strip, and the markets grid. All facts come from JSON. */
(async () => {
  const G = window.GC;
  const chartEl = G.$("hero-chart");
  const kpisEl = G.$("kpis");
  const gridEl = G.$("markets-grid");
  const trustEl = document.getElementById("trust-strip");

  let latest, history, metrics, extract;
  try {
    [latest, history, metrics, extract] = await Promise.all([
      G.fetchJSON("data/latest_forecasts.json"),
      G.fetchJSON("data/forecast_history.json"),
      G.fetchJSON("data/metrics.json"),
      G.fetchJSON("data/benchmark_extract.json").catch(() => ({ units: {} })),
    ]);
  } catch (e) {
    G.failState(chartEl.parentElement, e, () => location.reload());
    kpisEl.innerHTML = "";
    G.emptyState(gridEl, "");
    return;
  }

  const units = Object.keys(latest.units);
  const unitsMeta = latest.units_meta || {};
  const ordered = G.orderUnits(units, unitsMeta);
  const heroUnit = ordered[0];
  const heroSnap = latest.units[heroUnit];
  const heroMeta = unitsMeta[heroUnit] || {};

  // ---- trust strip ----
  const by = latest.generated_by || {};
  trustEl.innerHTML = "";
  const chips = [
    { k: "updated", v: G.fmtWhen(latest.generated_at) },
    { k: "book SHA", v: (by.git_sha || "?").slice(0, 7), title: "git sha of the code that wrote this data" },
    { k: "data through", v: (heroSnap.data_through || "").slice(0, 10), title: "freshest operator-published actual for the hero market" },
  ];
  for (const c of chips) {
    const el = document.createElement("span");
    el.className = "trust-chip";
    el.title = c.title || "";
    el.innerHTML = `<span class="k">${c.k}</span><span class="v">${c.v}</span>`;
    trustEl.appendChild(el);
  }

  // ---- hero chart ----
  chartEl.innerHTML = "";
  const traces = [G.demandTrace(heroSnap), ...G.intervalTraces(heroSnap), ...G.historyTraces(history ? history.days : [], heroUnit)];
  const layout = G.plotlyTheme();
  layout.yaxis.title = "MW";
  layout.margin = { t: 26, r: 10, b: 30, l: 52 };
  Plotly.react(chartEl, traces, layout, { responsive: true, displaylogo: false });

  // ---- KPI tiles ----
  const championVals = Object.entries(metrics.units).map(([u, m]) => [u, m]);
  let best = null;
  for (const [u, m] of championVals) {
    if (best === null || m.champion_value < best[1].champion_value) best = [u, m];
  }
  const countries = new Set(Object.values(latest.units).map((s) => s.market)).size;
  const points = Object.values(latest.units).reduce((a, s) => a + (s.n_fit_points || 0), 0);
  const streak = (history && history.days ? history.days.length : 0);
  const tiles = [
    best && {
      num: `${best[1].champion_value.toFixed(1)}%`,
      cap: `best measured accuracy — ${unitsMeta[best[0]] ? unitsMeta[best[0]].display_name : best[0]} (${best[1].primary_metric.replace("_pct", "")})`,
    },
    { num: `${units.length}`, cap: "market units forecast daily" },
    { num: `${countries}`, cap: "countries on 4 continents" },
    { num: `${G.fmtInt(Math.round(points / 1000))}k`, cap: `fit points today · ${streak} days straight` },
  ].filter(Boolean);
  kpisEl.innerHTML = "";
  for (const t of tiles) {
    const d = document.createElement("div");
    d.className = "kpi";
    d.innerHTML = `<div class="num">${t.num}</div><div class="cap">${t.cap}</div>`;
    kpisEl.appendChild(d);
  }

  // ---- markets grid ----
  gridEl.innerHTML = "";
  for (const u of ordered) {
    const m = unitsMeta[u];
    const card = document.createElement("a");
    card.className = "ucard-link";
    card.href = `explorer.html#${u}`;
    const mv = metrics.units[u];
    const d = mv ? G.fmtDelta(mv.naive_value, mv.champion_value, mv.primary_metric) : null;
    card.innerHTML = `
      <span class="u-flag">${m ? m.flag : ""}</span>
      <span class="u-name">${m ? m.display_name : u}</span>
      <span class="u-operator">${m ? m.operator : ""}</span>
      ${mv ? `<span class="delta ${d.cls}">${mv.champion_value.toFixed(2)} <small>${mv.primary_metric.replace("_pct", "%")}</small></span>`
          : `<span class="delta muted">soon</span>`}
      <span class="u-caveat">${m && m.caveat ? m.caveat.slice(0, 90) + (m.caveat.length > 90 ? "…" : "") : ""}</span>`;
    gridEl.appendChild(card);
  }
})();
