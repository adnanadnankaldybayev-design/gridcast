/* Dashboard — scoreboard: banner, market segments, main chart with
 * validation overlay, rolling-benchmark unit cards, horizon breakdown.
 * All market facts resolve through units_meta shipped by the data bundle. */
(async () => {
  const G = window.GC;
  const bannerEl = G.$("banner");
  const segEl = G.$("segments");
  const chartEl = G.$("chart");
  const cardsEl = G.$("units-grid");
  const metaEl = G.$("chart-meta");
  const subEl = G.$("chart-sub");
  const horizonEl = G.$("horizon-table");

  let latest, history, metrics, extract;
  try {
    [latest, history, metrics, extract] = await Promise.all([
      G.fetchJSON("data/latest_forecasts.json"),
      G.fetchJSON("data/forecast_history.json"),
      G.fetchJSON("data/metrics.json"),
      G.fetchJSON("data/benchmark_extract.json").catch(() => ({ units: {} })),
    ]);
  } catch (e) {
    G.failState(chartEl, e, () => location.reload());
    G.emptyState(cardsEl, "Benchmark bundle not published yet.");
    return;
  }

  const units = Object.keys(latest.units || {});
  if (!units.length) {
    G.emptyState(chartEl, "No forecast issued yet — the first daily run is pending.");
    return;
  }
  const unitsMeta = latest.units_meta || {};
  const order = G.orderUnits(units, unitsMeta);
  let current = order[0];

  // ---- banner: designed degrade states ----
  const degraded = latest.degraded || [];
  bannerEl.hidden = false;
  if (degraded.length) {
    bannerEl.className = "banner warn";
    bannerEl.innerHTML =
      `<b>graceful degrade</b> — ${degraded
        .map((d) => `<span class="badge">${d.unit}</span>`)
        .join(" ")} missed today's issue; those markets show their last valid day. Updated ${G.fmtWhen(latest.generated_at)}`;
  } else {
    bannerEl.className = "banner ok";
    const gb2 = latest.generated_by || {};
    const sha = gb2.git_sha ? gb2.git_sha.slice(0, 7) : "?";
    const dirty = gb2.git_dirty
      ? ` <span class="badge" title="tree was dirty when this bundle was written — sha does not fully pin the writer code">dirty tree</span>`
      : "";
    bannerEl.innerHTML =
      `<b style="color:var(--green)">healthy</b> — all ${units.length} units issued at ${G.fmtWhen(
        latest.generated_at
      )} · code <span title="git sha of the writer">${sha}</span>${dirty}`;
  }

  function renderSegments() {
    segEl.innerHTML = "";
    for (const u of order) {
      segEl.appendChild(
        G.segFor(u, unitsMeta[u] || {}, current, (unit) => {
          current = unit;
          renderSegments();
          renderChart();
          renderHorizon();
        })
      );
    }
  }

  function renderChart() {
    const snap = latest.units[current];
    if (!snap) return;
    if (G.plotlyOrFail(chartEl)) {
      const traces = [
        G.demandTrace(snap),
        ...G.intervalTraces(snap),
        ...G.historyTraces(history ? history.days : [], current),
      ];
      Plotly.react(chartEl, traces, G.plotlyTheme(), { responsive: true, displaylogo: false });
    }
    const m = metrics.units[current];
    const meta = unitsMeta[current] || {};
    const pair = m
      ? ` · ${m.primary_metric.replace("_pct", "")} ${m.champion_value.toFixed(2)} vs naive ${m.naive_value.toFixed(2)}`
      : "";
    metaEl.innerHTML =
      `<b>${current}</b> — ${meta.display_name || current} · ${snap.champion}${pair}<br>` +
      `issue ${snap.issue.slice(0, 16).replace("T", " ")} UTC · data through ${snap.data_through.slice(0, 16)}`;
    subEl.textContent = meta.caveat || "";
  }

  function renderCards() {
    cardsEl.innerHTML = "";
    for (const u of order) {
      const snap = latest.units[u];
      const mv = metrics.units[u];
      const btn = document.createElement("button");
      btn.className = "ucard" + (u === current ? " active" : "");
      let line = `<div class="u-model">${snap.champion} · latest</div>`;
      if (mv) {
        const d = G.fmtDelta(mv.naive_value, mv.champion_value, mv.primary_metric);
        line =
          `<div class="u-model">${snap.champion} vs naive</div>` +
          `<div class="delta ${d.cls}">${mv.champion_value.toFixed(2)} ${mv.primary_metric.replace(
            "_pct",
            "%"
          )} <span class="muted"> · naive ${mv.naive_value.toFixed(2)}</span></div>`;
      }
      btn.innerHTML =
        `<div class="u-head"><span class="fl">${unitsMeta[u] ? unitsMeta[u].flag : ""}</span>` +
        `<span class="u-code">${u}</span></div>${line}${
        G.sparkline((snap.published_demand_tail || []).map((p) => p.v))}`;
      btn.onclick = () => {
        current = u;
        renderSegments();
        renderChart();
        renderHorizon();
        window.scrollTo({ top: 0, behavior: "smooth" });
      };
      cardsEl.appendChild(btn);
    }
  }

  function renderHorizon() {
    const rec = extract.units && extract.units[current];
    if (!rec || !rec.by_horizon || !rec.by_horizon.length) {
      G.emptyState(horizonEl, "Horizon breakdown arrives with the next full benchmark commit.");
      return;
    }
    const maxVal = Math.max(...rec.by_horizon.map((r) => Math.max(r.champion, r.naive || 0)));
    const rows = rec.by_horizon
      .map((r) => {
        const w = (v) => Math.max(2, Math.round((v / maxVal) * 100));
        return `<div class="hz-row">
          <span class="hz-h">+${r.h}h</span>
          <span class="hz-bar"><i style="width:${w(r.champion)}%" class="c-champion"></i><b>${r.champion.toFixed(2)}</b></span>
          <span class="hz-bar"><i style="width:${w(r.naive || 0)}%" class="c-naive"></i><b>${(r.naive || 0).toFixed(2)}</b></span>
        </div>`;
      })
      .join("");
    horizonEl.innerHTML =
      `<div class="hz-legend"><span><i class="c-champion"></i> ${rec.champion_model}</span><span><i class="c-naive"></i> naive</span></div>${rows}`;
  }

  renderSegments();
  renderCards();
  renderChart();
  renderHorizon();
})();
