/* Country explorer — one profile card per market, driven entirely by
 * units_meta + benchmark extract + live snapshots. Hash = unit; KZ default. */
(async () => {
  const G = window.GC;
  const segEl = G.$("segments");
  const profileEl = G.$("profile");
  const miniChartEl = G.$("mini-chart");
  const benchEl = G.$("bench-content");

  let latest, extract;
  try {
    [latest, extract] = await Promise.all([
      G.fetchJSON("data/latest_forecasts.json"),
      G.fetchJSON("data/benchmark_extract.json").catch(() => ({ units: {} })),
    ]);
  } catch (e) {
    G.failState(profileEl, e, () => location.reload());
    return;
  }

  const unitsMeta = latest.units_meta || {};
  const units = Object.keys(latest.units || {});
  const order = G.orderUnits(units, unitsMeta);
  const fromHash = (location.hash || "").replace("#", "").trim();
  let current = units.includes(fromHash) ? fromHash : order[0];

  function renderSegments() {
    segEl.innerHTML = "";
    for (const u of order) {
      segEl.appendChild(
        G.segFor(u, unitsMeta[u] || {}, current, (unit) => {
          current = unit;
          history.replaceState(null, "", "#" + unit);
          renderAll();
        })
      );
    }
  }

  function renderProfile() {
    const meta = unitsMeta[current] || {};
    const snap = latest.units[current];
    const rec = extract.units && extract.units[current];
    const score =
      rec && rec.champion_value != null
        ? `<div class="kv"><span class="k">primary</span><span class="v">${
            rec.champion_value.toFixed(2)
          } ${rec.primary_metric.replace("_pct", "")}</span>
            <span class="muted"> · naive ${rec.naive_value == null ? "—" : rec.naive_value.toFixed(2)} · ${rec.champion_model}</span></div>`
        : "";
    profileEl.innerHTML = `
      <div class="profile-head">
        <span class="u-flag big">${meta.flag || ""}</span>
        <div>
          <h2>${meta.display_name || current} <span class="u-code">${current}</span></h2>
          <p class="muted">${meta.operator || ""} ·
            <a href="${meta.source_link || "#"}" rel="noopener">source ↗</a></p>
        </div>
      </div>
      <div class="kv-grid">
        <div class="kv"><span class="k">timezone</span><span class="v">${meta.tz || "—"}</span></div>
        <div class="kv"><span class="k">cadence</span><span class="v">${meta.cadence_min != null ? meta.cadence_min + " min" : "—"}</span></div>
        <div class="kv"><span class="k">publication lag</span><span class="v">${meta.pub_lag_days != null ? "~" + meta.pub_lag_days + " days" : "—"}</span></div>
        <div class="kv"><span class="k">primary metric</span><span class="v">${meta.primary_metric || "—"}</span></div>
        <div class="kv"><span class="k">published to</span><span class="v">${snap ? snap.data_through.slice(0, 10) : "—"}</span></div>
        <div class="kv"><span class="k">champion</span><span class="v">${snap ? snap.champion : "—"}</span></div>
      </div>
      ${meta.caveat ? `<div class="caveat-badge">${meta.caveat}</div>` : ""}
      ${score ? `<div class="profile-score">${score}</div>` : ""}
    `;
  }

  function renderMini() {
    const snap = latest.units[current];
    if (!snap) {
      G.emptyState(miniChartEl, "No snapshot for this unit yet.");
      return;
    }
    const traces = [G.demandTrace(snap), ...G.intervalTraces(snap)];
    const layout = G.plotlyTheme();
    layout.margin = { t: 20, r: 10, b: 20, l: 52 };
    layout.annotations = [{
      xref: "paper", yref: "paper", x: 0.01, y: 0.99, xanchor: "left", showarrow: false,
      text: "actual + 48h forecast", font: { color: layout ? "#8b949e" : "#8b949e", size: 11 },
    }];
    Plotly.react(miniChartEl, traces, layout, { responsive: true, displaylogo: false });
  }

  function renderBench() {
    const rec = extract.units && extract.units[current];
    if (!rec) {
      G.emptyState(benchEl, "Benchmark extract not published yet for this unit.");
      return;
    }
    const pm = rec.primary_metric.replace("_pct", "");
    const months = (rec.by_month || []);
    if (!months.length) {
      G.emptyState(benchEl, "No monthly benchmark rows for this unit.");
      return;
    }
    const rows = months
      .map((r) => {
        const better = r.champion < (r.naive == null ? Infinity : r.naive);
        return `<tr><td>${r.month}</td><td>${r.champion.toFixed(2)}</td>
          <td>${r.naive == null ? "—" : r.naive.toFixed(2)}</td>
          <td><span class="swatch ${better ? "good" : "warn"}" title="${better ? "champion better" : "naive better"}"></span></td></tr>`;
      })
      .join("");
    benchEl.innerHTML = `
      <table class="clean-table">
        <thead><tr><th>month</th><th>champion (${pm})</th><th>naive (${pm})</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="note">Swatch marks which model was better that month. Values from the last full benchmark run (${extract.git_sha || "—"}).</p>
    `;
  }

  function renderAll() {
    renderSegments();
    renderProfile();
    renderMini();
    renderBench();
  }

  window.addEventListener("hashchange", () => {
    const u = (location.hash || "").replace("#", "").trim();
    if (units.includes(u) && u !== current) {
      current = u;
      renderAll();}
    });

  renderAll();
})();
