/* GridCast dashboard v1 — reads site/data/{latest_forecasts,forecast_history,metrics}.json
   Render one market chart per selected unit:
   - actual tail (published demand, ends at data_through),
   - latest forecast with 80% and 90% interval bands,
   - previous days' forecasts from forecast_history (validation overlay).
   Fully static; no build step. */
(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat("en-GB");

  async function load(name) {
    const r = await fetch(`data/${name}?v=${Date.now()}`);
    if (!r.ok) throw new Error(`fetch ${name}: ${r.status}`);
    return r.json();
  }

  let latest, history, metrics;
  try {
    [latest, history, metrics] = await Promise.all([
      load("latest_forecasts.json"),
      load("forecast_history.json"),
      load("metrics.json").catch(() => ({ units: {} })),
    ]);
  } catch (e) {
    $("banner").textContent =
      "Dashboard data not generated yet — run `gridcast forecast` (or wait for the daily CI job).";
    $("banner").classList.add("degraded");
    return;
  }

  $("gen").textContent = "last generated: " + latest.generated_at;
  const units = Object.keys(latest.units);
  const degraded = latest.degraded || [];
  const streak = (history.days || []).length;
  $("headline").textContent =
    `${units.length} market units · ${streak} consecutive daily issues · models retrained daily`;
  const banner = $("banner");
  if (degraded.length) {
    banner.classList.add("degraded");
    banner.innerHTML = `⚠ Graceful degrade: ${degraded
      .map((d) => `<b>${d.unit}</b>`)
      .join(", ")} missed today's update — showing each market's last valid day anyway. Last issue: ${latest.issue}`;
  } else {
    banner.innerHTML = `<span class="live">✔ healthy</span> — all ${units.length} units updated at ${latest.generated_at}`;
  }

  // ---------- market picker ----------
  const order = ["KZ", "GB", "FR", "DE", "BE", "DK", "ALL", "KZ_W", "NEM_TOTAL",
                 "NSW1", "QLD1", "SA1", "TAS1", "VIC1"];
  const ordered = order.filter((u) => units.includes(u)).concat(
    units.filter((u) => !order.includes(u))
  );
  let current = ordered.includes("KZ") ? "KZ" : ordered[0];
  const picker = $("picker");
  for (const u of ordered) {
    const b = document.createElement("button");
    b.textContent = u;
    b.setAttribute("aria-pressed", u === current);
    b.onclick = () => {
      current = u;
      [...picker.children].forEach((c) =>
        c.setAttribute("aria-pressed", c.textContent === current)
      );
      render();
    };
    picker.appendChild(b);
  }

  // ---------- chart ----------
  const COLORS = {
    actual: "#58a6ff", forecast: "#3fb950", yesterday: "#d29922",
    band90: "rgba(63,185,80,0.18)", band80: "rgba(63,185,80,0.30)",
  };

  function xs(series, key = "t") {
    return series.map((p) => p[key].replace(" ", "T"));
  }
  function ys(series, key = "v") {
    return series.map((p) => p[key]);
  }

  function bandTrace(points, loKey, hiKey, color, name) {
    const x = xs(points);
    return [
      { x, y: ys(points, loKey), mode: "lines", line: { width: 0 },
        showlegend: false, hoverinfo: "skip", name: name + " lo" },
      { x, y: ys(points, hiKey), mode: "lines", line: { width: 0 },
        fill: "tonexty", fillcolor: color, name, hoverinfo: "skip" },
    ];
  }

  function render() {
    const u = latest.units[current];
    const traces = [];
    const actualX = u.published_demand_tail;
    traces.push({
      x: xs(actualX), y: ys(actualX),
      mode: "lines", line: { color: COLORS.actual, width: 2 },
      name: "actual (published operator data)",
    });
    const pts = u.points;
    traces.push(...bandTrace(pts, "lo90", "hi90", COLORS.band90, "90% interval"));
    traces.push(...bandTrace(pts, "lo80", "hi80", COLORS.band80, "80% interval"));
    traces.push({
      x: xs(pts), y: ys(pts, "pred"),
      mode: "lines", line: { color: COLORS.forecast, width: 2.5, dash: "solid" },
      name: `forecast (${u.champion})`,
    });

    // validation overlay: yesterday's forecast vs today's actual publication
    const histDays = (history.days || []).slice(-3);
    histDays.forEach((d, i) => {
      const e = d.units[current];
      if (!e || !e.points_short) return;
      const cap = d.date + " forecast";
      traces.push({
        x: xs(e.points_short), y: ys(e.points_short, "pred"),
        mode: i === histDays.length - 1 ? "lines" : "lines",
        line: { color: COLORS.yesterday, width: 1.5, dash: i === histDays.length - 1 ? "dot" : "dashdot" },
        opacity: 0.6 + 0.2 * i,
        name: cap,
      });
    });

    const layout = {
      paper_bgcolor: "#0d1117", plot_bgcolor: "#161b22",
      font: { color: "#e6edf3" },
      margin: { t: 30, r: 10, b: 40, l: 60 },
      xaxis: { gridcolor: "#30363d" },
      yaxis: { title: "MW", gridcolor: "#30363d", zerolinecolor: "#30363d" },
      legend: { orientation: "h", y: -0.18 },
      annotations: [{
        xref: "paper", yref: "paper", x: 0, y: 1.06, showarrow: false, xanchor: "left",
        text: `${current} — ${u.market} · issued ${u.issue} · data through ${u.data_through}`,
        font: { color: "#8b949e", size: 12 },
      }],
    };
    Plotly.react("chart", traces, layout, { responsive: true, displaylogo: false });
  }

  // ---------- metric cards ----------
  const m = $("metrics");
  for (const u of ordered) {
    const it = metrics.units[u];
    const div = document.createElement("div");
    div.className = "metric-sm";
    const champ = latest.units[u] ? latest.units[u].champion : "";
    if (it) {
      const delta = it.naive_value - it.champion_value;
      const good = delta > 0;
      div.innerHTML =
        `<div class="k">${u} · ${it.champion_model}</div>` +
        `<div class="v ${good ? "up" : "down"}">${it.champion_value.toFixed(2)} ${it.primary_metric.replace("_pct", "")}%</div>` +
        `<div class="k">naive ${it.naive_value.toFixed(2)} · ${good ? "beats" : "ties"} by ${Math.abs(delta).toFixed(2)}</div>`;
    } else {
      div.innerHTML = `<div class="k">${u} · ${champ}</div><div class="v">soon</div><div class="k">first benchmark pending</div>`;
    }
    m.appendChild(div);
  }

  render();
})();
