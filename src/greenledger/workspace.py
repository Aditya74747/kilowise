"""Upload workspace for another company's exports (used by `greenledger serve`, see README "Your own data").

Files uploaded in the app are checked against inputs.SPECS and saved to ROOT/workspace/raw. The build runs the normal
pipeline in a separate process with GL_WORKSPACE set, so every output lands in the workspace and the sample data,
its outputs and the app stay untouched. The app then opens /workspace/index.html with the workspace's data.js.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import inputs
from .config import DEFAULT_WORKSPACE, ROOT, SAMPLE_RAW, SETTINGS_DEFAULT, read_settings

MAX_BYTES = inputs.MAX_BYTES
_LOCK = threading.Lock()
_LAST: dict = {}


def folder() -> Path:
    v = os.environ.get("GL_UPLOAD_WORKSPACE", "").strip()
    return (Path(v) if Path(v).is_absolute() else ROOT / v) if v else DEFAULT_WORKSPACE


def raw() -> Path:
    return folder() / "raw"


def ws_app() -> Path:
    return folder() / "app"


def status() -> dict:
    r, files = raw(), []
    for name, spec in inputs.BY_NAME.items():
        p = inputs.path_for(r, name)
        row = {"file": name, "folder": spec["folder"], "present": p.exists()}
        if p.exists():
            row.update(size=p.stat().st_size, check=inputs.check_file(p))
        files.append(row)
    built = ws_app() / "data.js"
    return {"folder": str(folder().relative_to(ROOT)) if folder().is_relative_to(ROOT) else str(folder()),
            "files": files, "missing_required": inputs.missing_required(r),
            "settings": read_settings(folder()), "defaults": SETTINGS_DEFAULT,
            "built": built.exists(), "built_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(built.stat().st_mtime))
            if built.exists() else None, "last_build": _LAST or None, "building": _LOCK.locked()}


def save(name: str, body: bytes) -> dict:
    p = inputs.path_for(raw(), name)              # KeyError for any name not in the spec list: nothing else is written
    if len(body) > MAX_BYTES:
        raise ValueError("file too large")
    chk = inputs.check_text(body.decode("utf-8-sig", errors="replace"), name)
    if not chk["ok"]:
        return {**chk, "saved": False}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return {**chk, "saved": True}


def set_settings(s: dict) -> dict:
    allowed = {k: s[k] for k in SETTINGS_DEFAULT if k in s}
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / "settings.json").write_text(json.dumps(allowed, ensure_ascii=False, indent=1), encoding="utf-8")
    return status()


def load_sample() -> dict:
    """Copy the case files into the workspace: shows the whole upload-and-build flow with known numbers."""
    for name in inputs.BY_NAME:
        src = inputs.path_for(SAMPLE_RAW, name)
        if src.exists():
            dst = inputs.path_for(raw(), name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    return status()


def reset() -> dict:
    for sub in ("raw", "processed", "outputs", "app", "models"):
        shutil.rmtree(folder() / sub, ignore_errors=True)
    (folder() / "settings.json").unlink(missing_ok=True)
    _LAST.clear()
    return status()


def build(timeout: int = 900) -> dict:
    missing = inputs.missing_required(raw())
    if missing:
        return {**status(), "ok": False, "error": "required files missing: " + ", ".join(missing)}
    if not _LOCK.acquire(blocking=False):
        return {**status(), "ok": False, "error": "a build is already running"}
    try:
        t0 = time.time()
        env = {**os.environ, "GL_WORKSPACE": str(folder()), "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, "-m", "greenledger.cli", "build"], env=env, cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = (p.stdout + "\n" + p.stderr).strip().splitlines()
        err = next((line for line in reversed(out) if "Error" in line or "error" in line), "") if p.returncode else ""
        _LAST.clear()
        _LAST.update(ok=p.returncode == 0, seconds=round(time.time() - t0, 1), log=out[-12:], error=err,
                     at=time.strftime("%Y-%m-%d %H:%M"))
    finally:
        _LOCK.release()
    return {**status(), "ok": _LAST["ok"], "error": _LAST["error"]}
