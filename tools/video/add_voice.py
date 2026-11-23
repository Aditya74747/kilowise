"""Put the ElevenLabs voice-over on the demo video: one clip per chapter, placed at the chapter's start.

usage (from the repository root):
  uv run --no-project --with imageio-ffmpeg python tools/video/add_voice.py [folder with the clips]
  (default folder: tools/video/voice/; for example data/audio)

Reads  pitch/assets/kilowise_demo.mp4, pitch/assets/demo_chapters.js, tools/video/voice/NN_*.mp3 (sorted by name,
       one per chapter, in chapter order; see voiceover.md)
Writes pitch/assets/kilowise_demo_voice.mp4 (video copied unchanged, AAC audio)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS, VOICE = ROOT / "pitch" / "assets", Path(__file__).resolve().parent / "voice"
VIDEO, OUT = ASSETS / "kilowise_demo.mp4", ASSETS / "kilowise_demo_voice.mp4"
LEAD = 0.3          # seconds of silence after a chapter starts before its clip
MAX_SPEEDUP = 1.12  # a clip that is too long for its window is sped up at most this much


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg                                   # fallback: uv run --with imageio-ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration(ff: str, path: Path) -> float:
    err = subprocess.run([ff, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main() -> int:
    global VOICE
    if len(sys.argv) > 1:                                   # another folder of clips, e.g. data/audio
        VOICE = (ROOT / sys.argv[1]).resolve()
    ff = ffmpeg()
    js = (ASSETS / "demo_chapters.js").read_text(encoding="utf-8")
    chapters = json.loads(js[js.index("["):js.rindex("]") + 1])
    clips = sorted(VOICE.glob("*.mp3")) + sorted(VOICE.glob("*.wav"))
    clips.sort(key=lambda p: p.name)
    if len(clips) != len(chapters):
        print(f"need {len(chapters)} clips in {VOICE} (one per chapter: {', '.join(n for n, _ in chapters)}), "
              f"found {len(clips)}")
        return 1
    total = duration(ff, VIDEO)
    starts = [t for _, t in chapters] + [total]

    inputs, filters, ok = ["-i", str(VIDEO)], [], True
    print(f"{'chapter':<13}{'clip':>7}{'window':>8}  speed")
    for i, ((name, t), clip) in enumerate(zip(chapters, clips)):
        window = starts[i + 1] - t - LEAD - 0.2
        d = duration(ff, clip)
        speed = max(1.0, d / window)
        note = "" if speed <= 1.0 else f"x{speed:.2f}"
        if speed > MAX_SPEEDUP:
            note, ok, speed = f"TOO LONG by {d / MAX_SPEEDUP - window:.1f} s: shorten the text", False, MAX_SPEEDUP
        print(f"{name:<13}{d:>6.1f}s{window:>7.1f}s  {note}  ({clip.name})")
        inputs += ["-i", str(clip)]
        tempo = f"atempo={speed:.4f}," if speed > 1.0 else ""
        filters.append(f"[{i + 1}:a]{tempo}aresample=48000,adelay={round((t + LEAD) * 1000)}:all=1[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    graph = ";".join(filters) + f";{mix}amix=inputs={len(clips)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad,atrim=0:{total:.3f}[aout]"
    subprocess.run([ff, "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", str(OUT)], check=True)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    if not ok:
        print("one or more clips overlap the next chapter; shorten them and run again")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
