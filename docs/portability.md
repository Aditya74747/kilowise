# Portability: copy the project, run it anywhere

The project must run on any Windows, macOS or Linux machine after copying the folder or cloning the repository.

## Run on a new machine

1. Install [uv](https://docs.astral.sh/uv/) (one command, no admin rights needed).
2. Copy or clone the project folder. **Do not copy `.venv/`**; it is machine-specific and rebuilt by uv.
3. In the project folder:
   ```bash
   uv python pin 3.12           # writes .python-version (kept out of the public repository)
   uv sync                      # installs Python 3.12 and the locked dependencies (uv.lock),
                                # including the default groups dev (pytest) and ml (scikit-learn)
   uv run greenledger build     # data/raw → ML models → app/data.js, outputs/*.csv
   uv run pytest -q             # must be green
   uv run greenledger serve     # or open app/index.html directly in a browser
   ```
4. The app has no build step and no internet dependency: `app/index.html` works from disk.

## Rules for all code (checked by `tests/test_portability.py`)

1. **No absolute paths.** All paths come from `src/greenledger/config.py`, which derives them from the package location
   (`ROOT = Path(__file__).resolve().parents[2]`). Never write `C:\...`, `/Users/...` or a user name in code or config.
2. **`pathlib` only** for joining paths (`ROOT / "data" / "raw"`), never string concatenation with `\` or `/`.
3. **UTF-8 everywhere.** Every `open()`, `read_text()`, `write_text()` and `read_csv()` passes an explicit encoding
   (`utf-8`, or `utf-8-sig` for the case CSVs and the templates). Windows otherwise defaults to cp1252 and breaks on
   `CO₂`, `Δ`, `–`. The CLI reconfigures stdout to UTF-8.
4. **Pinned environment.** Python version in `.python-version` (local; the public repository leaves out dot-files, so
   run `uv python pin 3.12` after cloning), dependencies in `pyproject.toml`, exact versions in
   `uv.lock`. Add packages only with `uv add <pkg>` (optional ones in a dependency group: `uv add --group ml ...`).
   Fitted models (`models/**/*.joblib`) are not copied between machines: they are tied to library versions and are
   retrained automatically by `build` (seeded, so the results are the same).
5. **Secrets and machine settings only in environment variables** (e.g. `GL_CHAT_MODEL`, API keys). Document them in
   `.env.example` (local only, like every dot-file) and in docs/chatbot_rag_finetune.md; never commit `.env`.
6. **Generated files are reproducible.** `app/data.js`, `data/processed/`, `outputs/`, `app/downloads/` and `models/`
   are rebuilt by `uv run greenledger build` (and `train`). Seeds are fixed, so numbers are identical on every machine.
7. **Front end without external dependencies.** No CDN, no build tool; it must work offline from `file://`.
8. **No OS-specific commands** in the Python code (no `cmd`, PowerShell, `open`, `xdg-open`); use the standard library
   (`webbrowser`, `shutil`, `subprocess` with lists, not shell strings).
9. **Optional data degrades gracefully.** If `data/raw/extra/` or a model file is missing, the build still runs and
   says what was skipped.

## Before handing the project to someone else

- `uv run pytest -q` is green (includes the portability test).
- `uv run greenledger build` from a fresh copy works.
- No `.venv/`, `.env`, `__pycache__/` in the copy (see `.gitignore`).
