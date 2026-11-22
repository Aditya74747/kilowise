# Re-record the demo video after the app fixes of 22 Nov 2026

The current `pitch/assets/kilowise_demo.mp4` (recorded 22 Nov 00:32, 2:54) shows correct numbers everywhere, but it was
recorded before four interface bugs were fixed. Re-record it so the video matches the app. The general how-to is in
`README.md` in this folder; this file covers only what is specific to this re-record.

## 1. What is wrong in the current video

| Time in video | Chapter | What you see | Fixed in the app to |
|---|---|---|---|
| about 0:29–0:38 | IT team | "saas-other" twice in the hot list (250 kg and 92 kg); "All 57 resources" | One row per resource: "15 other SaaS contracts" 600 kg, 3rd place; "All 28 resources" |
| about 0:43–0:50 | Footprint | Location-based vs market-based bars overlap; Frankfurt's location bar is hidden; labels read market / location | Two thin bars side by side; labels read location / market like the legend |
| 1:35–1:57 | Kilo | Header cut off: "Answers from the ledger, computed in this p" | "Answers from your ledger" (full text on hover) |
| about 1:50 | Kilo | After Undo the button still says "Done: Drop M2 from the plan" | The button is clickable again after Undo |

Numbers that must stay the same in the new video (expected case): baseline CHF 465,668 · 36,108 kWh · 6,164 kg CO₂;
package −48.8 % CO₂, −33.4 % cost, 15 / 15 PD; payback 39 days; without M2 −21.1 % CO₂ / −27.7 % cost; high factors
−41.3 %; X1 stopped with 1,894 conflicts; M5 241 kg; vm-test 384 kg; dp-dev 1,871 kg.

Also fixed at the same time (not visible in the video, but good to know):

- Kilo now answers "Why is the dev cluster a problem?" without the server, from the dp-dev finding. Kilo also
  understands "production platform", "GPU server" and "test environment".
- Reports → "Our own AI use" now shows the computed values: 3–6 M tokens, 0.6–1.2 kWh, 0.13–0.26 kg CO₂. It used to
  show typed-in values (2–4 M tokens, 0.4–1 kWh).

## 2. Bring the fixes to the other PC

The fixes are in the working tree of the first PC and were **not committed** at the time of writing. Copy them across
first, either by committing and pushing (then pull on the other PC), or by copying these files:

- `app/app.js`, `app/app.css`, `app/index.html` (the fixes; index.html carries the new version tags)
- `tools/video/` (this folder), `pitch/` (the pitch page and assets)

Check that you have the fixed version: `app/app.js` contains `function resMerged()` and `const RES_ALIAS`.

## 3. Set up the other PC

- [uv](https://docs.astral.sh/uv/), then in the project folder: `uv sync`
- A browser. The scripts use **Google Chrome**, or else Playwright's Chromium. Without Chrome, run this once:
  `uv run --no-project --with playwright playwright install chromium`
  (On the first PC Chrome was missing; Edge works if you change `channel="chrome"` to `channel="msedge"` in
  `record_demo.py` and `make_stills.py`.)
- ffmpeg: either on the PATH (`winget install Gyan.FFmpeg`), or add `--with imageio-ffmpeg` to the commands below.

## 4. Record

From the project folder:

```bash
# keep the old video in case the new one has a problem (the mp4 is git-ignored, so there is no other copy)
cp pitch/assets/kilowise_demo.mp4 pitch/assets/kilowise_demo_old.mp4

uv run greenledger build                         # app/data.js must be current
uv run pytest -q                                 # must say 67 passed
uv run --no-project --with playwright --with imageio-ffmpeg python tools/video/record_demo.py   # about 5 min
uv run --no-project --with playwright python tools/video/make_stills.py                         # slide images + poster
```

`record_demo.py` also rewrites `pitch/assets/demo_chapters.js`. The pitch page's chapter buttons and speaker notes take
their times from it, so nothing else needs editing. If the script stops with `element not found: ...`, a heading changed:
fix the target in `scenes()` (see `README.md`).

## 5. Check the new video

Pull frames at the times above and look at them, e.g. with ffmpeg:

```bash
ffmpeg -ss 34 -i pitch/assets/kilowise_demo.mp4 -frames:v 1 check_hotlist.png
ffmpeg -ss 45 -i pitch/assets/kilowise_demo.mp4 -frames:v 1 check_market.png
ffmpeg -ss 110 -i pitch/assets/kilowise_demo.mp4 -frames:v 1 check_kilo.png
```

Chapter times shift a little; use the times in the new `demo_chapters.js` if a frame misses its scene. Check that:

- [ ] Hot list (IT team): each resource once; "15 other SaaS contracts" 600 kg in 3rd place; link says "All 28 resources"
- [ ] Footprint: the market card shows two separate bars per location; Frankfurt reads "2'306 kg / 2'872 kg"
- [ ] Kilo header reads "Answers from your ledger" in full
- [ ] After Undo, the button reads "Drop M2 from the plan" (no "Done:") and the message ends "Undone."
- [ ] The numbers listed in section 1 are unchanged
- [ ] Open `pitch/index.html`, go to the demo slide, press N: the chapter times match what plays
- [ ] The video is about 2:50 and 30–45 MB; delete `kilowise_demo_old.mp4` once you are happy
