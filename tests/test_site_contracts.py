"""Static site contracts pinned by the adversarial frontend review.

These guard against regressions of concrete defects found in review:
- seg buttons inside role="tablist" must carry role="tab" (ARIA tree validity)
- every Plotly.react call site must be guarded by plotlyOrFail (CDN blocked
  => designed degrade message, not silently blank charts)
- no market geography/truth claims hardcoded in JS (contract-first)
- no dead legacy bundles under site/js
"""

from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


def _js(name: str) -> str:
    return (SITE / "js" / name).read_text(encoding="utf-8")


def test_seg_buttons_carry_tab_role():
    src = _js("lib.js")
    assert 'setAttribute("role", "tab")' in src
    assert 'setAttribute("aria-selected"' in src


def test_every_plotly_call_site_is_guarded():
    for page in ("landing.js", "dashboard.js", "explorer.js", "forecast-page.js"):
        src = _js(page)
        assert "Plotly.react" in src, page
        assert "plotlyOrFail" in src, f"{page}: unguarded Plotly.react path"


def test_no_hardcoded_market_truths_in_shipped_js():
    joined = "\n".join(
        _js(n) for n in ("lib.js", "landing.js", "dashboard.js", "explorer.js", "forecast-page.js")
    )
    for claim in ("continents", "Kazakhstan", "NESO", "EirGrid", "KOREM"):
        assert claim not in joined, f"hardcoded fact in JS: {claim}"


def test_no_dead_js_bundles():
    assert not (SITE / "js" / "app.js").exists()


def test_landing_handles_empty_units_without_crash():
    src = _js("landing.js")
    # guard must run before ordered[0] / heroSnap dereference
    guard = src.index("if (!units.length)")
    deref = src.index("ordered[0]")
    assert guard < deref


def test_hero_aria_label_is_generic():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'aria-label="Live forecast chart for Kazakhstan trade zone"' not in html
    assert 'role="img"' in html


def test_order_units_runs_clean_under_node():
    """orderUnits crashed every data page at load (spread comparator calling
    .localeCompare on NaN) — regression pinned by executing the real function."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        import pytest

        pytest.skip("node not installed in this environment")
    script = (
        'const src = require("fs").readFileSync(process.argv[1], "utf8");'
        'const window = {}; eval(src);'
        'const meta = {'
        'IE: {country_code: "ie", display_name: "Ireland", flag: "x"},'
        'KZ: {country_code: "kz", display_name: "KZ North-South", flag: "x"},'
        'KZ_W: {country_code: "kz", display_name: "KZ West", flag: "x"},'
        'GB: {country_code: "gb", display_name: "Britain", flag: "x"}};'
        'const out = window.GC.orderUnits(Object.keys(meta), meta);'
        'if (out.join(",") !== "KZ,KZ_W,GB,IE") {'
        '  console.error("BAD ORDER: " + out.join(",")); process.exit(1);'
        '}'
    )
    proc = subprocess.run(
        ["node", "-e", script, str(SITE / "js" / "lib.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
