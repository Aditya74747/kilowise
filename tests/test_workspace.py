"""Your own data (requirements F10): input specs, upload checks, the server's write guard and the isolated workspace build."""
import functools
import http.client
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading

import pytest

from greenledger import cli, inputs, workspace
from greenledger.config import APP, ROOT, SAMPLE_RAW


def test_every_sample_export_matches_its_spec():
    for name in inputs.BY_NAME:
        chk = inputs.check_file(inputs.path_for(SAMPLE_RAW, name))
        assert chk["ok"], (name, chk)


def test_format_check_names_missing_columns_and_unknown_files():
    bad = inputs.check_text("month,eur_chf\n2026-01,0.94\n", "exchange_rates.csv")
    assert not bad["ok"] and bad["missing"] == ["usd_chf"]
    semi = inputs.check_text("month;eur_chf;usd_chf\n2026-01;0.94;0.88\n", "exchange_rates.csv")
    assert semi["ok"] and semi["rows"] == 1                    # ; separated exports are read too
    assert not inputs.check_text("a,b\n1,2\n", "evil.py")["ok"]
    with pytest.raises(KeyError):                               # uploads can only write the known file names
        inputs.path_for(ROOT / "workspace" / "raw", "../../src/greenledger/config.py")


def test_save_keeps_only_files_that_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("GL_UPLOAD_WORKSPACE", str(tmp_path))
    r = workspace.save("exchange_rates.csv", b"month,eur_chf\n2026-01,0.94\n")
    assert not r["saved"] and not (tmp_path / "raw" / "exchange_rates.csv").exists()
    good = (SAMPLE_RAW / "exchange_rates.csv").read_bytes()
    assert workspace.save("exchange_rates.csv", good)["saved"]
    st = workspace.status()
    assert "exchange_rates.csv" not in st["missing_required"] and len(st["missing_required"]) == 12


def test_server_refuses_writes_without_the_app_header(tmp_path, monkeypatch):
    monkeypatch.setenv("GL_UPLOAD_WORKSPACE", str(tmp_path))
    handler = functools.partial(cli._AppHandler, directory=str(APP))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def call(method, url, body=b"", headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request(method, url, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        assert call("POST", "/api/workspace/sample")[0] == 403                 # another web page cannot post here
        assert call("PUT", "/api/workspace/file?name=evil.py", b"x", {"X-GreenLedger": "1"})[0] == 400
        code, st = call("GET", "/api/workspace")
        assert code == 200 and len(st["files"]) == len(inputs.SPECS)
        srv.shutdown()


def test_workspace_build_is_isolated_and_uses_the_company_settings(tmp_path):
    ws = tmp_path / "ws"
    shutil.copytree(SAMPLE_RAW, ws / "raw", ignore=shutil.ignore_patterns("external"))
    (ws / "settings.json").write_text(json.dumps({"company": "Muster AG", "target_co2": 0.45, "pd_chf": 1200}),
                                      encoding="utf-8")
    sample_js = (APP / "data.js").stat().st_mtime
    env = {**os.environ, "GL_WORKSPACE": str(ws), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, "-m", "greenledger.cli", "build"], env=env, cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    d = json.loads((ws / "processed" / "app_data.json").read_text(encoding="utf-8"))
    assert d["meta"]["source"] == "workspace" and d["meta"]["company"] == "Muster AG"
    assert d["meta"]["targets"]["co2"] == 0.45 and d["meta"]["targets"]["pd_chf"] == 1200
    assert (ws / "app" / "data.js").exists() and (ws / "app" / "downloads" / "inputs" / "azure_costs.csv").exists()
    assert (ws / "outputs" / "template_measures_package.csv").exists()
    assert "target 45%" in (ws / "outputs" / "package_summary.txt").read_text(encoding="utf-8")
    assert (APP / "data.js").stat().st_mtime == sample_js       # the sample app data was not touched
    assert all(i["present"] and i["ok"] for i in d["inputs"])
