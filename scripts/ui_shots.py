"""UI screenshot harness: captures every site page at mobile (390x844) and
desktop (1440x900) into /tmp/shots_grey*. Pixels are then reviewed by the
agent itself — no screenshots are committed.

Run: .venv/Scripts/python.exe scripts/ui_shots.py http://127.0.0.1:8776
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8771"
PAGES = ["index.html", "dashboard.html", "explorer.html", "forecast.html", "methodology.html"]
SIZES = {
    "mobile": (390, 844),
    "desktop": (1440, 900),
}
OUT = Path("/tmp/gcshots")
OUT.mkdir(parents=True, exist_ok=True)


def shoot() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, (w, h) in SIZES.items():
            context = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=2 if name == "mobile" else 1,
                is_mobile=(name == "mobile"),
            )
            for page_name in PAGES:
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{BASE}/{page_name}", wait_until="networkidle")
                tgt = OUT / f"{page_name.replace('.html', '')}-{name}.png"
                page.screenshot(path=tgt, full_page=True)
                junk = "  ".join(f"[ERR {e}]" for e in errors[:2])
                print(f"{tgt.name:<36} ok{junk}")
                page.close()
            context.close()
        browser.close()


if __name__ == "__main__":
    os.makedirs("/tmp/gcshots", exist_ok=True)
    shoot()
