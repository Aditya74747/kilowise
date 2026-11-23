# Voice-over for the demo video (ElevenLabs)

The demo video (`pitch/assets/kilowise_demo.mp4`, 2:54) has no sound. This is the narration for the version that goes
to the submission form: one clip per chapter, each placed at its chapter's start by `add_voice.py`.

## Make it

1. In ElevenLabs (Text to Speech), pick one calm voice and keep the same voice and settings for all clips.
   Suggested: model *Eleven Multilingual v2*, stability about 50 %, similarity about 75 %, style 0, speed 1.0.
2. Generate the 12 clips below, one at a time, and download each as MP3 into `tools/video/voice/` with the file name
   shown (`01_overview.mp3`, `02_targets.mp3`, ...). The number at the start of the name sets the order.
3. Run:

   ```bash
   uv run --no-project --with imageio-ffmpeg python tools/video/add_voice.py              # clips in tools/video/voice/
   uv run --no-project --with imageio-ffmpeg python tools/video/add_voice.py data/audio   # or any other folder
   ```

   The voice is levelled to -16 LUFS (right for YouTube); the video itself is copied unchanged.

   It writes `pitch/assets/kilowise_demo_voice.mp4` and prints, per clip, how long it is against the time it has. A
   clip that runs too long is sped up slightly (at most 12 %); if one is still too long, shorten its text and generate
   it again.
4. Upload `kilowise_demo_voice.mp4` to YouTube as **Unlisted** and paste the link into the submission form.

Each text fits its window at a normal speaking pace (about 2.3 words per second) and leaves a short pause at the end.
Numbers are written as words so the voice reads them correctly.

## The clips

| File | Starts | Window | Text |
|---|---|---|---|
| `01_overview.mp3` | 0:01 | 15 s | This is Kilowise, running on the case company's exports. The answer comes first: our plan cuts CO2 by almost half and saves a third of the cost. Pick any period, and every figure follows. |
| `02_targets.mp3` | 0:16 | 13 s | Here are the three targets. Watch what happens if we drop one measure, the dev cluster pause: the CO2 target fails. Every measure counts. Back to the plan. |
| `03_it_team.mp3` | 0:29 | 9 s | The IT team gets its own view: the ten biggest CO2 sources, each with the change that fixes it. |
| `04_footprint.mp3` | 0:38 | 15 s | We count CO2 where the data centre stands. The same kilowatt hour is almost four times dirtier in Frankfurt than in Zurich. And every number opens up to show how it was calculated. |
| `05_insight.mp3` | 0:54 | 7 s | One finding: the development cluster runs day and night, but works only two hours a day. |
| `06_action_plan.mp3` | 1:01 | 16 s | Each measure in plain words: what it saves, the schedule before and after, and who decides. Twelve measures reach every target in fifteen person-days, and the plan holds even with pessimistic factors. |
| `07_safeguards.mp3` | 1:18 | 18 s | Kilowise knows its limits. Every new schedule is replayed against real job runs. Switching production off at night would break eighteen hundred and ninety-four jobs, so it is refused. And orders hidden in the data are ignored. |
| `08_kilo.mp3` | 1:35 | 21 s | Anyone can ask Kilo in plain words. What if we drop M two? It answers from the ledger, and suggests a change that only happens when you click. Undo is one click away. And when someone tries to slip in an order, Kilo blocks it. |
| `09_models.mp3` | 1:57 | 17 s | Choosing AI responsibly: twenty open and closed models, compared on the company's own usage, by price and CO2 per token, and even where they were trained and what that cost. |
| `10_grid.mp3` | 2:14 | 8 s | Europe's power grids, from open data, to move flexible work to cleaner places. |
| `11_reports.mp3` | 2:22 | 16 s | The two case templates download in one click, filled with the package. And we count our own AI use too: building Kilowise caused at most a quarter of a kilo of CO2. |
| `12_connectors.mp3` | 2:38 | 15 s | Next month, connect AWS, Azure, OpenAI, Claude and Microsoft 365, read-only, and the same checks run again. Kilowise: every kilowatt hour, accounted for. |

If the video is recorded again, the chapter times move a little; `add_voice.py` reads them from
`pitch/assets/demo_chapters.js`, so the clips follow automatically.
