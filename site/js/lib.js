/* GridCast shared front-end library — fetch/format/ui primitives only.
 * Renders only what site/data/*.json provides (plan §3.1 contract-first):
 * no market constants, names, corrections, or caveats live here. */
"use strict";

window.GC = (() => {
  const C = {
    actual: "#58a6ff",
    forecast: "#3fb950",
    band90: "rgba(63,185,80,0.15)",
    band80: "rgba(63,185,80,0.28)",
    prev: "#d29922",
    grid: "#21262d",
    fg: "#e6edf3",
    muted: "#8b949e",
  };

  const $ = (id) => document.getElementById(id);

  async function fetchJSON(path, { retries = 3 } = {}) {
    let lastErr = null;
    for (let i = 0; i < retries; i++) {
      try {
        const r = await fetch(path + "?v=" + Date.now(), { cache: "no-store" });
        if (!r.ok) throw new Error(path.split("/").pop() + " -> HTTP " + r.status);
        return await r.json();
      } catch (e) {
        lastErr = e;
        await new Promise((res) => setTimeout(res, 500 * (i + 1)));
      }
    }
    throw lastErr;
  }

  function failState(container, err, onRetry) {
    container.innerHTML = "";
    const div = document.createElement("div");
    div.className = "errbar";
    div.innerHTML =
      `<b>Data failed to load.</b> The dashboard is regenerated daily at 02:17 UTC —
      a failed fetch usually heals itself. (${String(err).slice(0, 90)})`;
    const btn = document.createElement("button");
    btn.className = "seg retry-btn";
    btn.textContent = "retry now";
    btn.onclick = onRetry;
    div.appendChild(btn);
    container.appendChild(div);
  }

  function emptyState(container, text) {
    container.innerHTML =
      `<div class="empty" role="status">${text ||
        "No data yet — appears after the next daily run."}</div>`;
  }

  const fmtInt = (n) => n.toLocaleString("en-GB");

  function fmtEnergy(mw, { digits = 1 } = {}) {
    if (mw == null || Number.isNaN(mw)) return "—";
    const abs = Math.abs(mw);
    if (abs >= 1000) return `${(mw / 1000).toLocaleString("en-GB", { maximumFractionDigits: digits })} GW`;
    return `${mw.toLocaleString("en-GB", { maximumFractionDigits: 0 })} MW`;
  }

  function fmtWhen(iso, { seconds = false } = {}) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (Number.isNaN(+d)) return iso;
      return (
        d.toLocaleString("en-GB", {
          day: "2-digit",
          month: "short",
          year: seconds ? "numeric" : undefined,
          hour: "2-digit",
          minute: "2-digit",
          timeZone: "UTC",
        }) + " UTC"
      );
    } catch {
      return iso;
    }
  }

  function plotlyTheme() {
    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#0d1117",
      font: { family: "Inter, sans-serif", color: C.fg, size: 12 },
      margin: { t: 8, r: 12, b: 36, l: 58 },
      showlegend: false,
      hovermode: "x unified",
      xaxis: { gridcolor: C.grid },
      yaxis: { title: "MW", gridcolor: C.grid, zerolinecolor: C.grid },
    };
  }

  function sparkline(vals, { w = 200, h = 42, stroke = C.actual } = {}) {
    if (!vals || vals.length < 2) return "";
    const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
    const pad = 2;
    const step = (w - 2 * pad) / (vals.length - 1);
    const pts = vals.map((v, i) => [pad + i * step, h - pad - ((v - min) / span) * (h - 2 * pad)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.4" opacity="0.85"/>
      <path d="${d} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z" fill="${stroke}" opacity="0.08" stroke="none"/></svg>`;
  }

  function plotlyAvailable() {
    return typeof window.Plotly !== "undefined";
  }

  function plotlyOrFail(el) {
    /* Called before every Plotly.react. With the CDN blocked/offline the
     * generic undefined-symbol crash otherwise leaves silently blank chart
     * areas — show the designed degrade state instead. */
    if (plotlyAvailable()) return true;
    failState(
      el,
      "chart engine (cdn.plot.ly) unreachable — text below still works",
      () => location.reload()
    );
    return false;
  }

  // ---- data primitives ----
  function orderUnits(units, unitsMeta) {
    // `withMeta` rows are [unit, meta] pairs — sort them directly (a mistaken
    // spread-based comparator crashed every data page on load, caught in review)
    const restSortOrder = (a, b) =>
      (a[1].country_code + a[1].display_name).localeCompare(b[1].country_code + b[1].display_name);
    const withMeta = units.map((u) => [u, unitsMeta[u]]).filter(([, m]) => m);
    const kzs = withMeta.filter(([, m]) => m.country_code === "kz").sort(restSortOrder);
    const rest = withMeta.filter(([, m]) => m.country_code !== "kz").sort(restSortOrder);
    return kzs.concat(rest).map(([u]) => u);
  }

  function segFor(unit, meta, current, onPick) {
    const b = document.createElement("button");
    b.className = "seg";
    // parents use role="tablist"; aria-selected is only valid on role="tab"
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", unit === current);
    const flagEl = document.createElement("span");
    flagEl.className = "fl";
    flagEl.textContent = meta.flag || "";
    const txt = document.createElement("span");
    txt.textContent = unit;
    b.append(flagEl, txt);
    b.onclick = () => onPick(unit);
    return b;
  }

  function isoList(points) {
    return points.map((p) => String(p.t).replace(" ", "T"));
  }

  function demandTrace(snap) {
    const tail = snap.published_demand_tail || [];
    return {
      x: isoList(tail),
      y: tail.map((p) => p.v),
      mode: "lines",
      line: { color: C.actual, width: 2 },
      name: "actual (published)",
    };
  }

  function intervalTraces(snap) {
    const pts = snap.points || [];
    const x = isoList(pts);
    const out = [];
    const band = (lo, hi, color, name) => {
      out.push({ x, y: pts.map((p) => p[lo]), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip", name: name + " lo" });
      out.push({ x, y: pts.map((p) => p[hi]), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: color, name, hoverinfo: "skip" });
    };
    if (pts.length && pts[0].lo90 != null) band("lo90", "hi90", C.band90, "90% interval");
    if (pts.length && pts[0].lo80 != null) band("lo80", "hi80", C.band80, "80% interval");
    out.push({
      x,
      y: pts.map((p) => p.pred),
      mode: "lines",
      line: { color: C.forecast, width: 2.4 },
      name: `forecast (${snap.champion})`,
    });
    return out;
  }

  function historyTraces(histDays, unit, { take = 3 } = {}) {
    const days = (histDays || []).slice(-take);
    return days
      .map((d, i) => {
        const e = d.units[unit];
        if (!e || !e.points_short) return null;
        return {
          x: isoList(e.points_short),
          y: e.points_short.map((p) => p.pred),
          mode: "lines",
          line: {
            color: C.prev,
            width: 1.3,
            dash: i === days.length - 1 ? "dot" : "dashdot",
          },
          opacity: 0.5 + 0.2 * i,
          name: `${d.date} issue`,
          showlegend: false,
          hoverinfo: "name+x+y",
        };
      })
      .filter(Boolean);
  }

  function fmtDelta(naive, champion, metric) {
    const d = naive - champion;
    const good = d > 0;
    const cls = good ? "good" : "warn";
    return { cls, delta: d, text: `${good ? "+" : "\u2212"}${Math.abs(d).toFixed(2)} vs naive` };
  }

  return {
    $,
    C,
    fetchJSON,
    failState,
    emptyState,
    fmtInt,
    fmtEnergy,
    fmtWhen,
    plotlyTheme,
    plotlyAvailable,
    plotlyOrFail,
    sparkline,
    orderUnits,
    segFor,
    demandTrace,
    intervalTraces,
    historyTraces,
    fmtDelta,
  };
})();
