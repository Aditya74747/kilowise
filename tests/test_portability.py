"""The project must run on any machine: no absolute paths, explicit UTF-8, paths from config.ROOT.
See docs/portability.md."""
import re

from greenledger.config import ROOT

CODE = [p for d in ("src", "tests", "app") for p in (ROOT / d).rglob("*")
        if p.suffix in (".py", ".js", ".html", ".css", ".toml") and p.name != "data.js" and "__pycache__" not in p.parts]
ABS_PATH = re.compile(r"""["'](?:[A-Za-z]:[\\/]|/Users/|/home/)""")
TEXT_IO = re.compile(r"\b(?:read_text|write_text|open)\(")


def test_config_paths_are_relative_to_project():
    from greenledger import config
    for name in ("RAW", "EXTRA", "PROCESSED", "OUTPUTS", "APP"):
        assert getattr(config, name).is_relative_to(ROOT), name
    assert (ROOT / "pyproject.toml").exists()


def test_no_absolute_paths_in_code():
    hits = [f"{p.relative_to(ROOT)}:{i}" for p in CODE for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if ABS_PATH.search(line)]
    assert not hits, hits


def test_text_io_has_explicit_encoding():
    hits = []
    for p in CODE:
        if p.suffix != ".py" or p.name == "test_portability.py":
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if TEXT_IO.search(line) and "webbrowser" not in line:
                call = " ".join(lines[i:i + 6])     # a call may span several lines
                if "encoding" not in call:
                    hits.append(f"{p.relative_to(ROOT)}:{i + 1}")
    assert not hits, hits
