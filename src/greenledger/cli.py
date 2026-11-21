"""Command line: `uv run greenledger build | serve | train | answer q1|q2|q3 | chat "question" | finetune | grid-fetch | pull`."""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import textwrap
import webbrowser

from .config import APP, APP_DATA, OUTPUTS, PROCESSED


def _build():
    from .export import build_all

    data = build_all()
    print((OUTPUTS / "package_summary.txt").read_text(encoding="utf-8"))
    print(f"App data  -> {APP_DATA / 'data.js'}")
    print(f"Templates -> {OUTPUTS}")
    return data


class _AppHandler(http.server.SimpleHTTPRequestHandler):
    """Static app + APIs (docs/chatbot_rag_finetune.md, README "Your own data").

    GET  /api/health, POST /api/chat {"question": ...}
    GET  /api/workspace                      status of the upload workspace (files, checks, settings, last build)
    PUT  /api/workspace/file?name=<export>   upload one export (only the file names in inputs.SPECS)
    POST /api/workspace/settings|sample|reset|build
    GET  /api/connectors                     connectors: state, which env variables are set (never their values), settings
    POST /api/connectors/config {id, values} save a connector's non-secret settings (scope, prices, department mapping)
    POST /api/connectors/pull {id, from, to} pull from a provider account into the workspace
    PUT  /api/connectors/focus               convert a FOCUS cost export into azure_costs.csv / aws_costs.csv
    /workspace/index.html serves the same app with the workspace's own data.js and downloads.
    Writes need the header X-GreenLedger: 1, so another web page cannot post here (no CORS answer is ever sent).
    """

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")          # a rebuilt data.js must never come from the cache
        super().end_headers()

    def translate_path(self, path):
        if path.startswith("/workspace/"):
            rest = path[len("/workspace"):]
            base = _workspace.ws_app() if rest.split("?")[0] == "/data.js" or rest.startswith("/downloads/") else APP
            saved, self.directory = self.directory, str(base)
            try:
                return super().translate_path(rest)
            finally:
                self.directory = saved
        return super().translate_path(path)

    def do_GET(self):
        if self.path.startswith("/api/health"):
            from . import chat
            return self._json(200, {**chat.status(), "loading": _LOADING.is_set(), "workspace_api": True})
        if self.path.startswith("/api/workspace"):
            return self._json(200, _workspace.status())
        if self.path.startswith("/api/connectors"):
            from . import connectors
            return self._json(200, connectors.status())
        return super().do_GET()

    def _body(self, limit: int) -> bytes:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > limit:
            raise ValueError(f"file too large ({n:,} bytes, limit {limit:,})")
        return self.rfile.read(n)

    def do_PUT(self):
        if self.path.startswith("/api/connectors/focus"):
            if self.headers.get("X-GreenLedger") != "1":
                return self._json(403, {"error": "missing X-GreenLedger header"})
            from . import connectors
            try:
                return self._json(200, connectors.import_focus(self._body(_workspace.MAX_BYTES).decode("utf-8-sig", errors="replace")))
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        if not self.path.startswith("/api/workspace/file"):
            return self._json(404, {"error": "not found"})
        if self.headers.get("X-GreenLedger") != "1":
            return self._json(403, {"error": "missing X-GreenLedger header"})
        from urllib.parse import parse_qs, urlsplit
        name = (parse_qs(urlsplit(self.path).query).get("name") or [""])[0]
        try:
            return self._json(200, _workspace.save(name, self._body(_workspace.MAX_BYTES)))
        except (KeyError, ValueError) as e:
            return self._json(400, {"error": str(e) if not isinstance(e, KeyError) else f"unknown file name {name!r}"})

    def do_POST(self):
        if self.path.startswith("/api/connectors/"):
            if self.headers.get("X-GreenLedger") != "1":
                return self._json(403, {"error": "missing X-GreenLedger header"})
            from . import connectors
            action = self.path.split("?")[0].rsplit("/", 1)[-1]
            try:
                body = json.loads(self._body(100_000).decode("utf-8") or "{}")
                if action == "config":
                    return self._json(200, connectors.set_config(str(body.get("id", "")), body.get("values") or {}))
                if action == "pull":
                    return self._json(200, connectors.pull(str(body.get("id", "")), body.get("from") or None, body.get("to") or None))
                return self._json(404, {"error": "not found"})
            except (KeyError, ValueError) as e:
                return self._json(400, {"error": f"{type(e).__name__}: {e}"})
        if self.path.startswith("/api/workspace/"):
            if self.headers.get("X-GreenLedger") != "1":
                return self._json(403, {"error": "missing X-GreenLedger header"})
            action = self.path.split("?")[0].rsplit("/", 1)[-1]
            try:
                body = json.loads(self._body(100_000).decode("utf-8") or "{}")
                fn = {"settings": lambda: _workspace.set_settings(body), "sample": _workspace.load_sample,
                      "reset": _workspace.reset, "build": _workspace.build}.get(action)
                return self._json(200, fn()) if fn else self._json(404, {"error": "not found"})
            except Exception as e:                # report, never crash the server
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        if not self.path.startswith("/api/chat"):
            return self._json(404, {"error": "not found"})
        from . import chat
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 20_000)
            q = json.loads(self.rfile.read(n).decode("utf-8") or "{}").get("question", "")
            return self._json(200, chat.answer(str(q)))
        except Exception as e:                    # never crash the server: the app falls back to its local engine
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):            # keep the console quiet except for API calls
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


from . import workspace as _workspace          # noqa: E402  (upload workspace for another company's exports)


_LOADING = __import__("threading").Event()


def _warm_up():
    from . import chat
    _LOADING.set()
    try:
        chat.retriever()
        m = chat.model()
        if m:                                     # first generation compiles kernels: do it before the first user
            chat.answer("What does the package save?")
        print(f"Chat: {m.name if m else 'retrieval only (' + str(chat.status()['error']) + ')'}")
    finally:
        _LOADING.clear()


def _serve(port: int, open_browser: bool):
    import threading
    if not (APP / "data.js").exists():
        _build()
    handler = functools.partial(_AppHandler, directory=str(APP))
    threading.Thread(target=_warm_up, daemon=True).start()       # load the chat model in the background
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        httpd.daemon_threads = True
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"Kilowise running at {url}  (Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)
        httpd.serve_forever()


def _chat(q: str):
    from . import chat
    from .rag import CHUNKS
    if not CHUNKS.exists():
        _build()
    a = chat.answer(q)
    print("\n" + textwrap.fill(a["text"], 100) + "\n")
    print(f"[{a['route']}{', ' + a['model'] if a.get('model') else ''} | {a.get('seconds', 0)} s | "
          f"~{a.get('energy_wh', 0):.3f} Wh]")
    if a.get("check") and a["check"]["removed"]:
        print("Removed (not in the facts):", ", ".join(a["check"]["removed"]))
    print("Sources:", "; ".join(a["sources"]) or "none")


def _finetune(epochs: float, eval_n: int, limit: int | None):
    from . import chat, finetune
    if not chat.deps_available():
        raise SystemExit("Install the optional group first: uv sync --group finetune")
    _build()                                     # facts and index must match the current numbers
    finetune.run(epochs=epochs, eval_n=eval_n, limit=limit)
    _build()                                     # fine-tuning energy into 'own AI use'; app shows the metrics


def _pull(cid: str | None, start: str | None, end: str | None, focus_file: str | None):
    from . import connectors
    if focus_file:
        from pathlib import Path
        r = connectors.import_focus(Path(focus_file).read_text(encoding="utf-8-sig"))
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return
    if not cid:
        for c in connectors.status()["connectors"]:
            env = ", ".join(f"{v['name']}{' (set)' if v['set'] else ''}" for v in c["env"]) or "none"
            print(f"{c['id']:<12} {c['state']:<12} {c['name']}  [env: {env}]")
        print("\nPull one: uv run greenledger pull <id> [--from YYYY-MM-DD --to YYYY-MM-DD]; files go to the workspace.")
        return
    r = connectors.pull(cid, start, end)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    if r.get("ok"):
        print("Then build the workspace in the app (Data sources > Build) or: GL_WORKSPACE=workspace uv run greenledger build")


def _grid_fetch():
    from . import grid

    print(f"Downloading Ember grid data to {grid.GRID_DIR} ...")
    for line in grid.fetch():
        print("  " + line)
    print("Run `uv run greenledger build` to update the Grid page.")


def _train():
    from . import ml

    res = ml.train(force=True)
    if res:
        c, f = res["classifier"], res["forecaster"]
        print(f"Classifier: {c['selected']}. {c['reason']}")
        for b, v in f["buckets"].items():
            print(f"Forecast {b}: {v['selected']}. {v['reason']}")
        print(f"Trained in {res['train_seconds']} s -> {ml.MODELS}")
        _build()


def _answer(q: str):
    p = PROCESSED / "app_data.json"
    if not p.exists():
        _build()
    data = json.loads(p.read_text(encoding="utf-8"))
    a = next(x for x in data["answers"] if x["id"].lower() == q.lower())
    print(f"\n{a['question']}\n")
    print(textwrap.fill(a["answer"], 100))
    for t in a.get("table", []):
        print("  ", t)
    if a.get("calculation"):
        print("\nCalculation:", textwrap.fill(a["calculation"], 100))
    print("\nSources:", "; ".join(a["sources"]))


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):   # print CO₂, ≈, – on any console (Windows cp1252, macOS, Linux)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from .config import load_env_file
    load_env_file()                                # secrets from .env (git-ignored), never printed
    ap = argparse.ArgumentParser(prog="greenledger", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build", help="clean data, compute baseline + measures, write app data and templates")
    s = sub.add_parser("serve", help="serve the app locally")
    s.add_argument("--port", type=int, default=8501)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("train", help="(re)train the ML models and keep the best per task (needs the `ml` group)")
    a = sub.add_parser("answer", help="answer an example question (q1, q2, q3)")
    a.add_argument("q", choices=["q1", "q2", "q3"])
    c = sub.add_parser("chat", help="ask the assistant (RAG + fine-tuned model; retrieval only without the model)")
    c.add_argument("question", nargs="+")
    f = sub.add_parser("finetune", help="build the training data, LoRA-train, evaluate, keep only if better "
                                        "(needs `uv sync --group finetune`)")
    f.add_argument("--epochs", type=float, default=2.0)
    f.add_argument("--eval", type=int, default=200, help="number of held-out test examples to evaluate")
    f.add_argument("--limit", type=int, default=None, help="use only the first N training examples (smoke test)")
    sub.add_parser("grid-fetch", help="download the newest European grid data (Ember, CC BY 4.0) for the Grid page")
    pl = sub.add_parser("pull", help="pull cost and usage from a connected account into the upload workspace")
    pl.add_argument("id", nargs="?", help="connector id (omit to list them)")
    pl.add_argument("--from", dest="start"); pl.add_argument("--to", dest="end")
    pl.add_argument("--focus", dest="focus_file", help="convert a FOCUS cost export CSV instead")
    args = ap.parse_args()
    if args.cmd == "serve":
        _serve(args.port, not args.no_browser)
    elif args.cmd == "answer":
        _answer(args.q)
    elif args.cmd == "train":
        _train()
    elif args.cmd == "chat":
        _chat(" ".join(args.question))
    elif args.cmd == "pull":
        _pull(args.id, args.start, args.end, args.focus_file)
    elif args.cmd == "grid-fetch":
        _grid_fetch()
    elif args.cmd == "finetune":
        _finetune(args.epochs, args.eval, args.limit)
    else:
        _build()


if __name__ == "__main__":
    main()
