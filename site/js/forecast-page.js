/* Forecast page — forward 48h view per unit with bands, horizon breakdown
 * bars from the benchmark extract, and a browser-computed backcast of the
 * last issues against what operators have since published. */
(async () => {
  const G = window.GC;
  const segEl = G.$("segments");
  const subEl = G.$("fc-sub");
  const chartEl = G.$("fc-chart");
  const horizonEl = G.$("horizon-table");
  const backcastEl = G.$("backcast");

  let latest, history, extract;
  try {
    [latest, history, extract] = await Promise.all([
      G.fetchJSON("data/latest_forecasts.json"),
      G.fetchJSON("data/forecast_history.json"),
      G.fetchJSON("data/benchmark_extract.json").catch(() => ({ units: {} })),
    ]);
  } catch (e) {
    G.failState(chartEl, e, () => location.reload());
    return;
  }

  const unitsMeta = latest.units_meta || {};
  const units = Object.keys(latest.units || {});
  if (!units.length) {
    G.emptyState(chartEl, "No forecast issued yet.");
    return;
  }
  const order = G.orderUnits(units, unitsMeta);
  let current = order[0];

  function renderSegments() {
    segEl.innerHTML = "";
    for (const u of order) {
      segEl.appendChild(
        G.segFor(u, unitsMeta[u] || {}, current, (unit) => {
          current = unit;
          renderAll();
        })
      );
    }
  }

  function renderChart() {
    const snap = latest.units[current];
    const traces = [...G.intervalTraces(snap), ...G.historyTraces(history ? history.days : [], current)];
    const layout = G.plotlyTheme();
    layout.yaxis.title = "MW";
    Plotly.react(chartEl, traces, layout, { responsive: true, displaylogo: false });
    const meta = unitsMeta[current] || {};
    const w = snap.weights
      ? ` · weights ${Object.entries(snap.weights)
          .map(([k, v]) => `${k} ${v.toFixed(2)}`)
          .join(" / ")}`
      : "";
    subEl.innerHTML =
      `<b>${meta.display_name || current}</b> · ${snap.champion}${w} · issue ${G.fmtWhen(snap.issue)} · data through ${snap.data_through.slice(0, 16)}${meta.caveat ? "<br>" + meta.caveat : ""}`;
  }

  function renderHorizon() {
    const rec = extract.units && extract.units[current];
    if (!rec || !rec.by_horizon || !rec.by_horizon.length) {
      G.emptyState(horizonEl, "Horizon split arrives with the next full benchmark commit.");
      return;
    }
    const maxV = Math.max(...rec.by_horizon.map((r) => Math.max(r.champion, r.naive || 0)));
    const rows = rec.by_horizon
      .map((r) => {
        const w = (v) => Math.max(2, Math.round((v / maxV) * 100));
        return `<div class="hz-row"><span class="hz-h">+${r.h}h</span>
          <span class="hz-bar"><i style="width:${w(r.champion)}%" class="c-champion"></i><b>${r.champion.toFixed(2)}</b></span>
          <span class="hz-bar"><i style="width:${w(r.naive || 0)}%" class="c-naive"></i><b>${(r.naive || 0).toFixed(2)}</b></span>
        </div>`;
      })
      .join("");
    horizonEl.innerHTML =
      `<div class="hz-legend"><span><i class="c-champion"></i> ${rec.champion_model}</span><span><i class="c-naive"></i> naive</span></div>${rows}`;
  }

  function renderBackcast() {
    const snap = latest.units[current];
    const tail = snap.published_demand_tail || [];
    const byTime = new Map(tail.map((p) => [p.t.replace(" ", "T"), p.v]));
    const allErr = [];
    for (const d of (history ? history.days : []).slice(-3)) {
      const e = d.units[current];
      if (!e || !e.points_short) continue;
      for (const p of e.points_short) {
        const key = p.t.replace(" ", "T");
        if (byTime.has(key)) {
          allErr.push({ t: key, err: p.pred - byTime.get(key), day: d.date });
        }
      }
    }
    if (!allErr.length) {
      G.emptyState(
        backcastEl,
        "No overlap yet between past issues and freshly published actuals — the operator lag keeps this honest and slow."
      );
      return;
    }
    allErr.sort((a, b) => a.t.localeCompare(b.t));
    const trace = {
      x: allErr.map((r) => r.t),
      y: allErr.map((r) => r.err),
      mode: "markers",
      marker: { size: 5, color: allErr.map((r) => Math.abs(r.err)), colorscale: "Viridis", showscale: true, colorbar: { title: "|err|" } },
      name: "forecast - actual",
    };
    const layout = G.plotlyTheme();
    layout.shapes = [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: 0, y1: 0, line: { color: G.C.grid } }];
    layout.yaxis.title = "error (MW)";
    Plotly.react(backcastEl, [trace], layout, { responsive: true, displaylogo: false });
  }

  function renderAll() {
    renderSegments();
    renderChart();
    renderHorizon();
    renderBackcast();
  }

  window.addEventListener("hashchange", renderAll);
  renderAll();
})();
