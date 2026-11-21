"""Front-end guards: the app loads the current files, its script is valid and wired to the page, no hidden characters."""
import hashlib
import re
import shutil
import subprocess

import pytest

from greenledger import export
from greenledger.config import APP, ROOT

FILES = [*APP.glob("*.js"), *APP.glob("*.css"), *APP.glob("*.html"), *(ROOT / "src" / "greenledger").glob("*.py"),
         *(ROOT / "tests").glob("*.py")]


def test_no_hidden_control_characters():
    """Escapes like \\b written through a shell can turn into real control bytes and silently break a regex."""
    for f in FILES:
        if f.name == "data.js":
            continue
        bad = [c for c in f.read_bytes() if c < 32 and c not in (9, 10, 13)]
        assert not bad, f"{f.name}: control bytes {sorted(set(bad))}"


def test_index_loads_the_current_files():
    """The build stamps app.css / app.js / data.js with their content hash, so a browser never shows an old copy."""
    export.stamp_index()
    html = (APP / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js", "data.js"):
        m = re.search(rf'"{re.escape(name)}\?v=([0-9a-f]+)"', html)
        assert m, f"{name} is not versioned in index.html"
        assert m.group(1) == hashlib.sha1((APP / name).read_bytes()).hexdigest()[:10], f"{name}: stale version"


def test_every_element_the_script_uses_exists():
    js = (APP / "app.js").read_text(encoding="utf-8")
    html = (APP / "index.html").read_text(encoding="utf-8")
    used = set(re.findall(r"\$\('#([A-Za-z][\w-]*)'\)", js))
    defined = set(re.findall(r'id="([A-Za-z][\w-]*)"', html)) | set(re.findall(r'id=\\?"([A-Za-z][\w-]*)\\?"', js))
    assert not used - defined, f"ids used in app.js but never created: {sorted(used - defined)}"


def test_navigation_order_and_old_links():
    js = (APP / "app.js").read_text(encoding="utf-8")
    nav = re.findall(r"\{ id: '(\w+)', label: '([^']+)'", js)
    assert [label for _, label in nav] == ["Overview", "Action plan", "Safeguards", "Insights", "Footprint", "Models", "Grid", "Reports",
                                           "Data sources", "Lab", "Sources"]
    for old in ("plan", "safeguards", "insights", "footprint", "reports", "lab"):
        assert f"{old}: '" in js, f"old link #{old} is not mapped"


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js not installed")
def test_script_parses():
    p = subprocess.run(["node", "--check", str(APP / "app.js")], capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr


def test_overview_has_leadership_and_it_dashboards():
    """Case owner feedback: one holistic leadership dashboard and a separate IT dashboard on the Overview."""
    js = (APP / "app.js").read_text(encoding="utf-8")
    for name in ("function ceoBody(", "function itBody(", "function forecastWithPlan(", "function savingsList(", "const kcard =", "function rangeBar(", "function periodFigures(",
                 "id=\"aud\"", "id=\"mList\"", "id=\"rbA\"", "id=\"rbB\""):
        assert name in js, f"{name} missing"
    assert "ceo: 'Leadership', it: 'IT team'" in js


def test_stylesheet_rules_are_closed():
    """A rule whose first line was deleted leaves a stray } that silently drops the next rule."""
    depth = 0
    for n, line in enumerate((APP / "app.css").read_text(encoding="utf-8").splitlines(), 1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"app.css line {n}: closing brace without an open rule"
    assert depth == 0, "app.css: a rule is never closed"


def test_models_page_is_wired():
    js = (APP / "app.js").read_text(encoding="utf-8")
    for name in ("function renderModels(", "function mdMonth(", "function mdScatter(", "models: renderModels", "id=\"mdGrid\""):
        assert name in js, f"{name} missing"
