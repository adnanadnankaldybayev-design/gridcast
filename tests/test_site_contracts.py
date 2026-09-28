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
