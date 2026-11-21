"""Paths and global settings.

Two modes:
- sample (default): the case data in data/raw, outputs in data/processed, outputs/ and app/.
- workspace: set GL_WORKSPACE to a folder (relative to the project root or absolute). Its raw/ holds another
  company's exports and its settings.json the company's baseline year and targets; every output goes into the
  workspace too, so the sample stays untouched. `greenledger serve` uses ROOT/workspace for uploads from the app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"                             # the app's code (index.html, app.js, app.css)
SAMPLE_RAW = ROOT / "data" / "raw"
SHARED_PROCESSED = ROOT / "data" / "processed"   # reference_cache.json lives here in both modes

_ws = os.environ.get("GL_WORKSPACE", "").strip()
WORKSPACE = (Path(_ws) if Path(_ws).is_absolute() else ROOT / _ws) if _ws else None
DEFAULT_WORKSPACE = ROOT / "workspace"         # where `serve` keeps files uploaded in the app (gitignored)

if WORKSPACE:
    RAW = WORKSPACE / "raw"
    PROCESSED = WORKSPACE / "processed"
    OUTPUTS = WORKSPACE / "outputs"
    APP_DATA = WORKSPACE / "app"               # data.js + downloads/ for /workspace/index.html
    MODELS_DIR = WORKSPACE / "models"
else:
    RAW = SAMPLE_RAW
    PROCESSED = SHARED_PROCESSED
    OUTPUTS = ROOT / "outputs"
    APP_DATA = APP
    MODELS_DIR = ROOT / "models"
EXTRA = RAW / "extra"

# Defaults = the case: baseline year September 2025 to August 2026, targets -40 % CO2, -25 % cost, 15 PD.
SETTINGS_DEFAULT = {"company": "Sample SME, Basel (synthetic data, ALTYCA / sprintd Basel 2026)",
                    "baseline_start": "2025-09-01", "data_as_of": "2026-09-06", "target_co2": 0.40,
                    "target_cost": 0.25, "budget_pd": 15, "pd_chf": 1100}


def read_settings(folder: Path | None) -> dict:
    """Workspace settings.json merged over the defaults; unknown keys and bad values are ignored."""
    s = dict(SETTINGS_DEFAULT)
    p = folder / "settings.json" if folder else None
    if p and p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            user = {}
        for k, v in (user.items() if isinstance(user, dict) else []):
            if k not in s or v in (None, ""):
                continue
            try:
                s[k] = str(v) if isinstance(s[k], str) else type(s[k])(float(v))
            except (TypeError, ValueError):
                pass
    return s


SETTINGS = read_settings(WORKSPACE)
COMPANY = (SETTINGS["company"] if SETTINGS["company"] != SETTINGS_DEFAULT["company"] else "Your company") \
    if WORKSPACE else SETTINGS_DEFAULT["company"]
BASELINE_START = pd.Timestamp(SETTINGS["baseline_start"]).to_period("M").to_timestamp()
BASELINE_END = BASELINE_START + pd.DateOffset(years=1) - pd.Timedelta(days=1)
DATA_AS_OF = pd.Timestamp(SETTINGS["data_as_of"])

PERSON_DAY_CHF = int(SETTINGS["pd_chf"])
BUDGET_PERSON_DAYS = float(SETTINGS["budget_pd"])
TARGET_CO2 = float(SETTINGS["target_co2"])
TARGET_COST = float(SETTINGS["target_cost"])
if BUDGET_PERSON_DAYS == int(BUDGET_PERSON_DAYS):
    BUDGET_PERSON_DAYS = int(BUDGET_PERSON_DAYS)

SCENARIOS = ("low", "mid", "high")
# CO2 views. Location-based: Swiss grid mix "consumption" (incl. imports, default) or "production".
# "market" = market-based view (bonus): guarantees of origin / residual mix. Targets are location-based only.
LOCATION_MIXES = ("consumption", "production")
CH_MIX_VARIANTS = (*LOCATION_MIXES, "market")


# ---- Optional AI part (docs/chatbot_rag_finetune.md). Model choice only via environment variables.
EXTERNAL = SAMPLE_RAW / "external"             # open datasets + reference documents (see data/raw/external/README.md)
CHAT_ADAPTER_DIR = ROOT / "models" / "chat-lora"   # one adapter for both modes (it learns behaviour, not figures)


def load_env_file(path: Path | None = None) -> list[str]:
    """Read KEY=VALUE lines from ROOT/.env into the environment (variables already set win). Returns the names set,
    never the values. .env is git-ignored; secrets for the connectors and the chat model live there or in the shell."""
    p = path or ROOT / ".env"
    if not p.exists():
        return []
    names = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k):
            os.environ[k] = v
            names.append(k)
    return names


def env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def chat_base_model() -> str:
    return env("GL_CHAT_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")


def embed_model() -> str:
    return env("GL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


def chat_provider() -> str:
    """local = fine-tuned small model on this machine; none = retrieval-only answers (no model call)."""
    return env("GL_CHAT_PROVIDER", "local").lower()


def in_baseline(s: pd.Series) -> pd.Series:
    return (s >= BASELINE_START) & (s <= BASELINE_END + pd.Timedelta(hours=23, minutes=59))
