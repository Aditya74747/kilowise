"""Sources page: every reference is complete and used, every factor is referenced or a stated assumption."""
import json

from greenledger import factors as F
from greenledger.config import PROCESSED


def _s():
    return json.loads((PROCESSED / "app_data.json").read_text(encoding="utf-8"))["sources"]


def test_references_are_complete_numbered_and_used():
    s = _s()
    refs = s["references"]
    assert len({r["id"] for r in refs}) == len(refs) and [r["n"] for r in refs] == list(range(1, len(refs) + 1))
    for r in refs:
        assert r["publisher"] and r["title"] and r["kind"] in s["kinds"], r["id"]
        assert r["url"] or r["note"], r["id"]                    # a link, or a note on how to find it
        assert r["used_for"], f"{r['id']} is listed but nothing uses it"


def test_every_factor_is_referenced_or_a_stated_assumption():
    s = _s()
    assert len(s["factors"]) == len(F.ALL_FACTORS)
    for f in s["factors"]:
        if not f["refs"]:
            assert "assumption" in f["source"].lower(), f"{f['key']} has no reference and is not marked as an assumption"
    n = {r["n"] for r in s["references"]}
    assert all(set(f["refs"]) <= n for f in s["factors"])


def test_open_data_licences_are_stated():
    s = _s()
    for r in s["references"]:
        if r["kind"] == "open":
            assert r["licence"], r["id"]
