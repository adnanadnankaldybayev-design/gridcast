/* GridCast dashboard (vanilla, no build step).
 * Reads site/data/{latest_forecasts,forecast_history,metrics}.json.
 * Sections: partial renderers (header/KPIs/segments/main chart/unit cards),
 * skeletons->content, retry on fetch failure, graceful-degrade banner.
 * Data contract is intentionally unchanged (tests pin it). */
(() => {
  const $ = (id) => document.getElementById(id);
  const C = {
    green: "#3fb950",
    cyan: "#39c5cf",
    amber: "#d29922",
    accent: "#58a6ff",
    grid: "#21262d",
    fg: "#e6edf3",
    muted: "#8b949e",
  };
  const FLAGS = {
    GB: "\u{1F1EC}\u{1F1E7}", ALL: "\u{1F1EE}\u{1F1EA}", FR: "\u{1F1EB}\u{1F1F7}",
    DE: "\u{1F1E9}\u{1F1EA}", BE: "\u{1F1E7}\u{1F1EA}", DK: "\u{1F1E9}\u{1F1F0}",
    KZ: "\u{1F1F0}\u{1F1FF}", KZ_W: "\u{1F1F0}\u{1F1FF}",
    NEM_TOTAL: "\u{1F1E6}\u{1F1FA}", NSW1: "\u{1F1E6}\u{1F1FA}",
    QLD1: "\u{1F1E6}\u{1F1FA}", SA1: "\u{1F1E6}\u{1F1FA}",
    TAS1: "\u{1F1E6}\u{1F1FA}", VIC1: "\u{1F1E6}\u{1F1FA}",
  };
  const NAMES = {
    GB: "Great Britain (NESO)", ALL: "Ireland, All-Island (EirGrid)",
    FR: "France (RTE)", DE: "Germany (SMARD)", BE: "Belgium (Elia)",
    DK: "Denmark (Energinet)", KZ: "Kazakhstan, North–South zone (KOREM)",
    KZ_W: "Kazakhstan, West zone (KOREM)",
    NEM_TOTAL: "Australia NEM total (AEMO)",
    NSW1: "Australia — New South Wales", QLD1: "Australia — Queensland",
    SA1: "Australia — South Australia", TAS1: "Australia — Tasmania", VIC1: "Australia — Victoria",
  };
  const SUBTEXT = {
    KZ: "Clearing-trade demand of centralized trades — an off-take view of KOREM's market, not the physical grid load.",
    KZ_W: "Clearing-trade demand, West zone — trade-side volume from KOREM, not physical grid load.",
    GB: "National demand; operator actuals reach us ~21 days late by design.",
    DK: "Industry-settlement consumption; publishes ~18 days late.",
    BE: "Transmission offtake; midday solar depressions are real physics.",
    FR: "Definitive archive was 30-minute until Jun 2026 (operator's design).",
  };

  let LATEST = null;
  let HISTORY = null;
  let METRICS = null;
  let current = null;
  const orderedFor = (units) => {
    const order = ["KZ", "GB", "FR", "DE", "BE", "DK", "ALL", "KZ_W", "NEM_TOTAL",
                   "NSW1", "QLD1", "SA1", "TAS1", "VIC1"];
    return order.filter((u) => units.includes(u)).concat(units.filter((u) => !order.includes(u)));
  };

  async function fetchJSON(path, retries = 3) {
    let err = null;
    for (let i = 0; i < retries; i++) {
      try {
        const r = await fetch(path + "?v=" + Date.now(), { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
      } catch (e) {
        err = e;
        await new Promise((res) => setTimeout(res, 600 * (i + 1)));
      }
    }
    throw err;
  }

  function failState(e) {
    $("live-pill").classList.remove("live");
    $("live-text").textContent = "offline";
    const bar = $("errbar");
    bar.hidden = false;
    bar.className = "banner err";
    bar.innerHTML =
      "Couldn't load the dashboard data. " +
      "It is regenerated daily at 02:17 UTC; if this persists, the run failed. " +
      `<button class="retry" id="retry-btn">retry (${String(e).slice(0, 80)})</button>`;
    $("retry-btn").onclick = () => location.reload();
    $("chart").innerHTML =
      `<div class="card" style="text-align:center;color:var(--muted)">chart unavailable until data loads (${String(e) === "404" ? "no data files yet — first CI run pending" : "fetch error"})</div>`;
  }

  function fmtNum(n, dp = 1) {
    return n == null ? "—" : n.toLocaleString("en-GB", { maximumFractionDigits: dp });
  }

  function fmtWhen(iso) {
    try {
      return new Date(iso).toLocaleString("en-GB", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
      }) + " UTC";
    } catch {
      return iso;
    }
  }

  // ---------- header ----------
  function renderHeader() {
    const units = Object.keys(LATEST.units);
    const degraded = LATEST.degraded || [];
    const days = (HISTORY.days || []).length;
    $("live-pill").classList.add(degraded.length ? "" : "live");
    $("live-text").textContent = degraded.length ? `degraded ×${degraded.length}` : "live";
    $("c-markets").textContent = `${units.length} markets online`;
    $("c-days").textContent = `${days} days streak`;
    $("c-when").textContent = `updated ${fmtWhen(LATEST.generated_at)}`;
    const b = $("banner");
    if (degraded.length) {
      b.hidden = false;
      b.className = "banner warn";
      b.innerHTML =
        `⚠ Graceful degrade — ${degraded.map((d) => `<b>${d.unit}</b>`).join(", ")} ` +
        `didn't update today; those markets show their last valid day. Everything else is fresh.`;
    } else {
      b.hidden = false;
      b.className = "banner ok";
      b.innerHTML = `<b style="color:var(--green)">✔ healthy</b> — all ${units.length} market units refreshed at ${fmtWhen(LATEST.generated_at)};
        issue point ${LATEST.issue.replace("T", " ").slice(0, 16)} UTC.`;
    }
  }

  // ---------- KPI row ----------
  function renderKPIs() {
    const units = Object.keys(LATEST.units);
    let best = null;
    for (const [u, m] of Object.entries(METRICS.units)) {
      const v = m.champion_value;
      if (best === null || v < best.v) best = { u, v, champ: m.champion_model, metric: m.primary_metric };
    }
    const countries = new Set(Object.values(LATEST.units).map((s) => s.market)).size;
    const points = Object.values(LATEST.units).reduce((a, s) => a + (s.n_fit_points || 0), 0);
    const kpiBox = $("kpis");
    kpiBox.innerHTML = "";
    const items = [
      best && {
        num: `${best.v.toFixed(1)}<small>${best.metric.replace("_pct", "%")}</small>`,
        cap: `best measured accuracy — ${best.u} (${best.champ})`,
      },
      { num: `${units.length}<small>units</small>`, cap: "markets observed daily" },
      { num: `${countries}<small>countries</small>`, cap: "on 4 data continents" },
      { num: `${fmtNum(Math.round(points / 1000), 0)}k<small>points</small>`, cap: "fit points used today (150-day windows)" },
    ].filter(Boolean);
    for (const it of items) {
      const d = document.createElement("div");
      d.className = "kpi";
      d.innerHTML = `<div class="num">${it.num}</div><div class="cap">${it.cap}</div>`;
      kpiBox.appendChild(d);
    }
  }

  // ---------- segments ----------
  function renderSegments() {
    const wrap = $("segments");
    wrap.innerHTML = "";
    for (const u of orderedFor(Object.keys(LATEST.units))) {
      const b = document.createElement("button");
      b.className = "seg";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", u === current);
      b.innerHTML = `<span class="flag">${FLAGS[u] || ""}</span><span>${u}</span>`;
      b.onclick = () => {
        current = u;
        [...wrap.children].forEach((c) => {
          const code = c.getElementsByTagName("span")[1].textContent;
          c.setAttribute("aria-selected", code === current);
        });
        renderCards();
        renderChart();
      };
      if (u === current) b.setAttribute("aria-selected", true);
      wrap.appendChild(b);
    }
  }

  // ---------- unit cards ----------
  function sparkline(vals) {
    if (!vals || vals.length < 2) return "";
    const w = 200, h = 42, pad = 2;
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = max - min || 1;
    const step = (w - 2 * pad) / (vals.length - 1);
    const pts = vals.map((v, i) => [pad + i * step, h - pad - ((v - min) / span) * (h - 2 * pad)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <path d="${d}" fill="none" stroke="${C.accent}" stroke-width="1.4" opacity="0.85"/>
      <path d="${d} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z" fill="${C.accent}" opacity="0.08" stroke="none"/></svg>`;
  }

  function renderCards() {
    const grid = $("units-grid");
    grid.innerHTML = "";
    for (const u of orderedFor(Object.keys(LATEST.units))) {
      const s = LATEST.units[u];
      const m = METRICS.units[u];
      const btn = document.createElement("button");
      btn.className = "ucard" + (u === current ? " active" : "");
      let metricLine = `<div class="u-model">${s.champion}${s.weights ? " · ensemble" : ""} · latest</div>`;
      if (m) {
        const delta = m.naive_value - m.champion_value;
        const good = delta > 0;
        metricLine =
          `<div class="u-model">${s.champion} vs naive</div>` +
          `<div class="delta ${good ? "good" : "warn"}">${m.champion_value.toFixed(2)} ${m.primary_metric.replace("_pct", "%")}
           <span style="color:var(--muted);font-weight:500"> · naive ${m.naive_value.toFixed(2)}</span></div>`;
      }
      const spark = sparkline(s.published_demand_tail.map((p) => p.v));
      btn.innerHTML =
        `<div class="u-head"><span class="u-code">${FLAGS[u] || ""} ${u}</span></div>
         ${metricLine}${spark}`;
      btn.onclick = () => {
        current = u;
        renderSegments();
        renderCards();
        renderChart();
        window.scrollTo({ top: 0, behavior: "smooth" });
      };
      grid.appendChild(btn);
    }
    $("units-note").textContent = ` — click a card to focus the main chart`;
  }

  // ---------- main chart ----------
  function tracesFor(u) {
    const s = LATEST.units[u];
    const tail = s.published_demand_tail || [];
    const pts = s.points || [];
    const clean = (arr) => arr.map((p) => p.t.replace(" ", "T"));
    const out = [];
    out.push({
      x: clean(tail), y: tail.map((p) => p.v),
      mode: "lines",
      line: { color: C.accent, width: 2 },
      name: "actual (published)",
    });
    if (pts.length && pts[0].lo90 != null) {
      out.push({
        x: clean(pts), y: pts.map((p) => p.lo90),
        mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip",
        name: "90% lo",
      });
      out.push({
        x: clean(pts), y: pts.map((p) => p.hi90),
        mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(63,185,80,0.15)", name: "90% interval", hoverinfo: "skip",
      });
      out.push({
        x: clean(pts), y: pts.map((p) => p.lo80),
        mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip",
        name: "80% lo",
      });
      out.push({
        x: clean(pts), y: pts.map((p) => p.hi80),
        mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(63,185,80,0.28)", name: "80% interval", hoverinfo: "skip",
      });
    }
    out.push({
      x: clean(pts), y: pts.map((p) => p.pred),
      mode: "lines",
      line: { color: C.green, width: 2.5 },
      name: `forecast (${LATEST.units[u].champion})`,
    });
    return out;
  }

  function historyTraces(u) {
    const days = (HISTORY.days || []).slice(-3);
    return days.map((d, i) => {
      const e = d.units[u];
      if (!e || !e.points_short) return null;
      return {
        x: e.points_short.map((p) => p.t.replace(" ", "T")),
        y: e.points_short.map((p) => p.pred),
        mode: "lines",
        line: {
          color: C.amber, width: 1.4,
          dash: i === days.length - 1 ? "dot" : "dashdot",
        },
        opacity: 0.55 + 0.2 * i,
        hoverinfo: "name+x+y",
        name: `${d.date} issue`,
        showlegend: false,
      };
    }).filter(Boolean);
  }

  function renderChart() {
    const u = current;
    const s = LATEST.units[u];
    if (!s || !(s.points || []).length || !(s.published_demand_tail || []).length) {
      $("chart").innerHTML =
        `<div class="empty" style="padding:64px;text-align:center;color:var(--muted)">
          No forecast available for ${u} yet — shown as soon as the champion has enough published history.</div>`;
      return;
    }
    const traces = [...tracesFor(u), ...historyTraces(u)];
    const mean48 = Math.round(s.points.reduce((a, p) => a + p.pred, 0) / s.points.length);
    const through = s.data_through.replace(" ", "T").slice(0, 16) + "Z";
    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#0d1117",
      font: { family: "Inter, sans-serif", color: C.fg, size: 12 },
      margin: { t: 8, r: 12, b: 36, l: 58 },
      showlegend: false,
      hovermode: "x unified",
      xaxis: {
        gridcolor: C.grid,
        rangeslider: { visible: false },
      },
      yaxis: { title: "MW", gridcolor: C.grid, zerolinecolor: C.grid },
      annotations: [{
        xref: "paper", yref: "paper", x: 0, y: -0.15, showarrow: false,
        xanchor: "left", font: { color: C.muted, size: 11 },
        text: `${u} — ${NAMES[u] || u} · issue ${s.issue.slice(0, 16).replace("T", " ")} UTC · data through ${through}`,
      }],
    };
    Plotly.react("chart", traces, layout, { responsive: true, displaylogo: false });
    $("chart-meta").innerHTML =
      `<b>${u}</b> · ${s.champion}${s.weights ? "" : ""} · horizon ${s.horizon_h}h ·
       mean 48h forecast <b>${mean48.toLocaleString("en-GB")} MW</b><br>
       <span title="models retrain on today's freshest published point">fit points ${s.n_fit_points.toLocaleString("en-GB")}</span>`;
    $("chart-sub").textContent = SUBTEXT[u] || "";
  }

  // ---------- boot ----------
  async function boot() {
    try {
      const [latest, history, metrics] = await Promise.all([
        fetchJSON("data/latest_forecasts.json"),
        fetchJSON("data/forecast_history.json"),
        fetchJSON("data/metrics.json").catch(() => ({ units: {} })),
      ]);
      LATEST = latest;
      HISTORY = history;
      METRICS = metrics;
      if (!latest.units || !Object.keys(latest.units).length) {
        throw new Error("latest_forecasts.json has no units (empty issue?)");
      }
      current = orderedFor(Object.keys(LATEST.units))[0];
      const tasks = [renderHeader, renderKPIs, renderSegments, renderCards, renderChart];
      for (const t of tasks) t();
    } catch (e) {
      failState(e);
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
