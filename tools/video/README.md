# Demo video and pitch: how to rebuild them

Context for anyone (or any Claude session) who has to remake the pitch video or the pitch slides on another machine.
Everything is generated from the real app by scripts in this folder; nothing is edited by hand in a video tool.

## What exists

| File | What it is | Made by |
|---|---|---|
| `pitch/index.html` | The pitch: full-screen slides for a 5-minute pitch with the demo video embedded. Open it in Chrome from disk. | written by hand |
| `pitch/assets/kilowise_demo.mp4` | Demo video, 1920×1080, 60 fps, H.264, about 2:50, **no captions and no sound**: paced for the presenter to talk over it | `record_demo.py` |
| `pitch/assets/demo_chapters.js` | Start time of each scene in the video; the pitch page builds its chapter buttons and the speaker notes from it | `record_demo.py` |
| `pitch/assets/*.jpg` | App stills for the slides (dashboard, rule engine, models chart, grid map, Kilo, calculation panel) and the video poster | `make_stills.py` |
| `pitch/assets/HankenGrotesk-var.ttf` | The app's typeface (SIL Open Font License, `OFL.txt`), so the pitch works offline | copied from `app/fonts/` |

## Rebuild (from the repository root)

Needs: Google Chrome, [uv](https://docs.astral.sh/uv/), ffmpeg on the PATH (Windows: `winget install Gyan.FFmpeg`; macOS:
`brew install ffmpeg`; or add `--with imageio-ffmpeg` to the commands below, the script then uses its bundled ffmpeg).
Playwright is pulled in for the run only; it is not a project dependency.

```bash
uv run greenledger build                                                        # app/data.js must be current
uv run --no-project --with playwright python tools/video/record_demo.py         # video + chapters (about 5 min)
uv run --no-project --with playwright python tools/video/make_stills.py         # slide images + video poster
```

`--fps 30` makes a quicker draft. `--pace` (default 1.3) slows every movement, `--stay` (default 1.3) lengthens
every pause on a spotlight; raise them if the presenter needs more time per scene. Without Google Chrome: `uv run --with playwright playwright install chromium` once;
the scripts fall back to Playwright's Chromium.

## How the recorder works (`record_demo.py`)

- Opens `app/index.html` straight from disk (no server). Kilo answers with its in-browser engine, so no model is needed.
- CSS viewport 1536×864 at device scale 1.25 gives 1920×1080 pixels with the app's normal desktop layout.
- **Frame by frame, not screen capture:** for every frame the script sets the state (cursor position, spotlight box,
  click ripple, scroll position), paints it with an injected overlay (`window.V.frame`) and takes a screenshot. Motion
  uses cubic ease-in-out, so the video is smooth however fast the machine is. A still moment is one capture repeated
  for its exact number of frames; all frames are piped to ffmpeg at a constant 60 fps. Do not go back to the concat
  demuxer with per-image durations: its rounding dropped or doubled frames and made cursor moves look choppy.
- Real clicks drive the app (`click()` calls `element.click()` after the drawn cursor arrives).
- **Overlay elements:** cursor, click ripple, download confirmation (top right), spotlight.
- **Look:** a neutral spotlight (the page dims slightly, a thin white outline and soft shadow around the element), a
  white arrow cursor, and a soft grey ripple on clicks. No captions, no title cards, no brand-coloured glow.
- Targets are CSS selectors or `text:<heading>`, which means "the card around the heading that starts with this text".
  If a heading or id in the app changes, the script stops with `element not found: ...`; fix the target in `scenes()`.

## The scenes (in pitch order)

| Chapter | What happens |
|---|---|
| Overview | Verdict line, key figures; Last 6 months, then back to Baseline year |
| Targets | Target gauges; untick M2, the CO₂ gauge fails; Reset |
| IT team | IT team tab, hot list of the 10 largest CO₂ sources |
| Footprint | "By location" (same kWh, different grid); open the calculation panel of the top resource |
| Insight | The dev-cluster finding (24/7 at 9 % activity) |
| Action plan | The selected measure in plain words (what you get, before and after, why it is safe); target check; View → High factors: still on target; back to Mid |
| Safeguards | The four checks, the crash-test bars (X1 stopped), the hidden orders marked "Ignored" |
| Kilo | Types "What if we drop M2?", clicks "Drop M2 from the plan" (status turns red), Undo; injected order blocked |
| Models | Comparison cards, cost-against-CO₂ chart, training CO₂ chart |
| Grid | Scrolls until the whole Europe map is in view, spotlight on the map |
| Reports | Clicks two template downloads (a browser-style download confirmation shows the real file name and size; the
link itself is stopped so the page stays), our own AI use |
| Connectors | Data sources, scrolls to "Connect your accounts": AWS, Azure, OpenAI, Claude, Microsoft 365, FOCUS, other SaaS |

To change the story, edit `scenes()`: each `mark("Name")` starts a chapter. A new chapter name also needs a sentence in
`SAY` in `pitch/index.html` (the speaker notes for the demo slide), otherwise its button is hidden.

## The pitch page (`pitch/index.html`)

- Keys: arrows / space / scroll = next and back, **N** = speaker notes with timings, **F** = full screen, **K** or **P** =
  pause the video on the demo slide. The video starts by itself when its slide opens and pauses when you leave it.
- Slides and timing for 5 minutes (one light, card-based style throughout; the story is accountability, not numbers):
  title 10 s, challenge 20 s (opens with one sentence on why it matters), demo about 2:55, answers 20 s (the four things
  the case wants to see: overall picture, one finding, the package against target and budget, one edge case), what
  changes 20 s, why it lasts 20 s, close 10 s (about 4:35, leaving some room for transitions).
- Numbers on the slides are the expected case (mid factors, Swiss consumption mix) from `CLAUDE.md` "Current results".
  If a measure or factor changes, update the slide numbers and re-record the video.
- Look: off-white background, white cards with soft shadows, green icon tiles; brand green `#146c53`, deep green `#0b2a21`
  for the few dark bands, warm accent only for the "seen in the case data" story.

## Checks after a rebuild

- Pull a few frames and look at them: `ffmpeg -ss 30 -i pitch/assets/kilowise_demo.mp4 -frames:v 1 check.png`.
- Open `pitch/index.html`, press N on the demo slide: the chapter times must match what you see in the video.
- The video is about 30–40 MB; it is git-ignored (`pitch/assets/*.mp4`). Share it separately (e.g. an unlisted YouTube
  link for the submission form).
