"""Still images of the app for the pitch slides: element screenshots at 2x, written to pitch/assets/.

usage (from the repository root):
  uv run --no-project --with playwright python tools/video/make_stills.py
"""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
APP, OUT = ROOT / "app" / "index.html", ROOT / "pitch" / "assets"
OUT.mkdir(parents=True, exist_ok=True)
FIND = """s => { const h = [...document.querySelectorAll('#main h2, #main h3')].find(x => x.textContent.trim().startsWith(s));
  const e = h && (h.closest('.block, .card, section') || h); if (e && !e.id) e.id = 'vtarget'; return e ? '#' + e.id : null; }"""

with sync_playwright() as p:
    try:
        b = p.chromium.launch(channel="chrome")
    except Exception:
        b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)

    def tab(t: str, q: str = ""):
        pg.goto(APP.as_uri() + q + "#" + t)
        pg.wait_for_timeout(900)

    def wide(name: str, sel: str, top: float = 0.0):
        """A 16:9 crop as wide as the element, starting `top` (share of its height) below its top edge. The three
        'Why it lasts' cards in the pitch show their image in a 16:9 box, so these fit exactly without cropping."""
        r = pg.evaluate("s => { const r = document.querySelector(s).getBoundingClientRect(); "
                        "return {x: r.x, y: r.y + scrollY, width: r.width, height: r.height}; }", sel)
        clip = {"x": r["x"], "y": r["y"] + r["height"] * top, "width": r["width"], "height": round(r["width"] * 9 / 16)}
        pg.screenshot(path=str(OUT / name), type="jpeg", quality=90, clip=clip, full_page=True)
        print("wrote", name)

    def shot(name: str, sel: str | None = None, text: str | None = None, clip: dict | None = None):
        if text:
            sel = pg.evaluate(FIND, text)
        if clip:
            pg.screenshot(path=str(OUT / name), type="jpeg", quality=90, clip=clip)
        else:
            pg.locator(sel).first.screenshot(path=str(OUT / name), type="jpeg", quality=90)
        pg.evaluate("document.querySelectorAll('#vtarget').forEach(e => e.removeAttribute('id'))")
        print("wrote", name)

    tab("start", "?view=ceo")
    shot("app_overview.jpg", clip={"x": 0, "y": 0, "width": 1440, "height": 900})
    shot("overview_targets.jpg", text="Targets")
    tab("limits")
    shot("injections.jpg", sel=".sg-notes")
    shot("safeguards_flow.jpg", sel=".sg-flow")
    pg.set_viewport_size({"width": 1280, "height": 900})   # at this width check 2 (heading + crash-test bars) is 16:9
    tab("limits")
    wide("rule_engine.jpg", "#sg-test")
    pg.set_viewport_size({"width": 1440, "height": 900})
    tab("models")
    shot("models_scatter.jpg", text="Cost against CO₂")
    shot("training.jpg", sel="#trChart")
    tab("grid")
    wide("grid_map.jpg", "#main .gr-geo", top=0.27)       # central Europe: Dublin, Frankfurt, Zurich
    tab("connect")
    pg.evaluate("document.querySelector('#main tr.click').click()")
    pg.wait_for_timeout(400)
    wide("calc_panel.jpg", "#panel", top=0.117)           # figures + the start of the quantity-to-CO2 chain
    tab("start", "?view=ceo&ask=What%20if%20we%20drop%20M2%3F")
    pg.wait_for_timeout(800)
    shot("kilo.jpg", sel="#ai")
    b.close()

# poster frame of the video (if it exists): the first second
video = OUT / "kilowise_demo.mp4"
ff = shutil.which("ffmpeg")
if video.exists() and ff:
    subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(video), "-frames:v", "1", "-q:v", "3",
                    str(OUT / "demo_cover.jpg")], check=True)
    print("wrote demo_cover.jpg")
