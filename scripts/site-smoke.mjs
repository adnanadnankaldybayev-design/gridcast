// GridCast site smoke for CI: drive all 5 data pages through jsdom against
// the REAL site/data/*.json and fail on any JS error (the TypeError class of
// bugs that orderUnits hid once already). Plotly is stubbed with a minimal
// Plotly.predict-and-forget global; everything else is executed for real.
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM, ResourceLoader } from "jsdom";

const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "site");

const PLOTLY_STUB = `
window.Plotly = {
  react: (el, traces, layout, opts) => Promise.resolve({ el: el, traces: traces }),
  purge: () => {},
};
`;

class LocalResourceLoader extends ResourceLoader {
  fetch(url, options) {
    const u = String(url);
    if (u.startsWith("https://cdn.plot.ly/")) {
      return Promise.resolve(Buffer.from(PLOTLY_STUB));
    }
    if (u.startsWith("http://localhost/")) {
      const rel = u.replace("http://localhost/", "").split("?")[0];
      const file = join(SITE, rel || "index.html");
      if (existsSync(file)) return Promise.resolve(readFileSync(file));
    }
    if (!u.startsWith("http")) {
      const rel = u.replace(/^\.\//, "").split("?")[0];
      const file = join(SITE, rel);
      if (existsSync(file)) return Promise.resolve(readFileSync(file));
    }
    return super.fetch(url, options);
  }
}

const PAGES = ["index.html", "dashboard.html", "explorer.html", "forecast.html", "methodology.html"];

async function runPage(pageName) {
  const html = readFileSync(join(SITE, pageName), "utf8");
  const errors = [];
  const dom = new JSDOM(html, {
    url: "http://localhost/" + pageName,
    runScripts: "dangerously",
    resources: new LocalResourceLoader(),
    pretendToBeVisual: true,
    beforeParse(win) {
      // jsdom's own URL resolution does not read our "data/..." bundle from
      // disk: shim fetch() with jsdom-independent globalThis.Response and a
      // UTF-8 string body (verified shape) so pages hit the REAL committed
      // data — none of it mocked.
      win.fetch = async (resource) => {
        const rsrc = typeof resource === "string" ? resource : resource && resource.url;
        if (typeof rsrc === "string" && !rsrc.startsWith("http")) {
          const file = join(SITE, rsrc.split("?")[0]);
          if (existsSync(file)) {
            return new globalThis.Response(readFileSync(file, "utf8"), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            });
          }
          return new globalThis.Response("missing", {
            status: 404,
            headers: { "Content-Type": "text/plain" },
          });
        }
        return new globalThis.Response("external fetches blocked in smoke", {
          status: 599,
          headers: { "Content-Type": "text/plain" },
        });
      };
    },
  });
  const win = dom.window;
  win.addEventListener("error", (e) => errors.push(e.error || e.message || "unknown error"));
  win.addEventListener("unhandledrejection", (e) => errors.push(e.reason || "rejection"));
  await new Promise((resolve) => setTimeout(resolve, 1500));

  const documentTitle = win.document.title;
  const fatal = errors.filter(Boolean);
  const checks = [];
  if (pageName === "index.html") {
    const trust = win.document.getElementById("trust-strip");
    checks.push(["landing trust-strip populated", !!trust && trust.children.length >= 2]);
    checks.push(["landing KPIs populated", win.document.getElementById("kpis").children.length > 0]);
    checks.push(["landing hero chart non-empty state", !!win.document.querySelector("#hero-chart")]);
  }
  if (pageName === "dashboard.html") {
    const banner = win.document.getElementById("banner");
    checks.push(["banner populated (degrade or ok)", !!(banner && banner.textContent.trim().length > 0)]);
    checks.push(["segments populated", win.document.getElementById("segments").children.length > 0]);
    checks.push(["unit cards populated", win.document.getElementById("units-grid").children.length > 0]);
  }
  if (pageName === "explorer.html") {
    const profile = win.document.getElementById("profile");
    checks.push(["profile populated", !!(profile && profile.textContent.includes("timezone"))]);
  }
  if (pageName === "forecast.html") {
    const segs = win.document.getElementById("segments");
    checks.push(["forecast segments populated", !!(segs && segs.children.length > 0)]);
  }
  if (pageName === "methodology.html") {
    const rows = win.document.querySelectorAll("#src-table tr");
    checks.push(["sources table populated from units_meta", rows.length >= 10]);
  }
  const badChecks = checks.filter(([, ok]) => !ok);
  win.close();
  return { page: pageName, title: documentTitle, fatal, badChecks };
}

let failures = 0;
for (const page of PAGES) {
  try {
    const r = await runPage(page);
    const issues = [
      ...r.fatal.map((e) => `js error: ${String(e).slice(0, 160)}`),
      ...r.badChecks.map(([name]) => `assert failed: ${name}`),
    ];
    if (issues.length === 0) {
      console.log(`PASS ${page} (${r.title})`);
    } else {
      failures++;
      console.log(`FAIL ${page} (${r.title})`);
      for (const msg of issues) console.log("   -", msg);
    }
  } catch (e) {
    failures++;
    console.log(`FAIL ${page} -- runner crashed: ${String(e).slice(0, 200)}`);
  }
}
process.exitCode = failures > 0 ? 1 : 0;
