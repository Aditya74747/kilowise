"""Connectors: pull cost and usage from cloud, AI and SaaS accounts into the exports Kilowise reads.

Used by the Data sources page (`greenledger serve`, /api/connectors) and by `greenledger pull`. Pulled data goes into the
upload workspace (workspace/raw), never into the sample data: the same format check and the same isolated build as for
uploaded files follow.

Safety rules (also in README "Connect your accounts"):
  * read-only: each connector lists the narrowest permission it needs;
  * secrets only in environment variables (or .env, never committed); the app only ever sees whether a variable is set;
  * settings that are not secret (scope, prices, department mapping) live in workspace/connectors.json;
  * a pull replaces only the rows of its own source and period, so several sources can feed one file
    (OpenAI and Anthropic both write ai_usage.csv).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import time
from pathlib import Path

import pandas as pd

from .. import inputs
from . import focus, providers

# id, name, category, target file, how, env vars (all required), optional python package, settings, permission, steps, docs
CONNECTORS = [
    {"id": "focus", "name": "FOCUS cost export (any cloud)", "category": "Cloud", "targets": ["azure_costs.csv", "aws_costs.csv"],
     "how": "file", "env": [], "package": None,
     "settings": [],
     "permission": "None: you export the file yourself.",
     "steps": ["AWS: Billing and Cost Management > Data Exports > create export, type 'FOCUS 1.2', CSV, daily, to an S3 bucket.",
               "Azure: Cost Management > Exports > 'Cost and usage details (FOCUS)', CSV, daily, to a storage account.",
               "Google Cloud: query the FOCUS view of the billing export in BigQuery and save as CSV (rows are reported; "
               "the ledger has no Google reader yet).",
               "Drop the CSV here. Resource IDs, regions, sizes and tags come through; units become vCPU-hours and GB-days."],
     "docs": "https://focus.finops.org/"},
    {"id": "aws_ce", "name": "AWS Cost Explorer", "category": "Cloud", "targets": ["aws_costs.csv"], "how": "api",
     "env": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"], "env_alt": ["AWS_PROFILE"], "package": "boto3",
     "settings": [],
     "permission": "IAM policy with only ce:GetCostAndUsage (read-only).",
     "steps": ["Create an IAM user or role with a policy that allows only ce:GetCostAndUsage.",
               "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (or AWS_PROFILE) in .env or the shell.",
               "Install the optional packages: uv sync --group connectors.",
               "Pull. Daily cost by service and usage type; instance sizes become vCPU-hours. For resource IDs and tags use "
               "the FOCUS export."],
     "docs": "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html"},
    {"id": "azure_cost", "name": "Azure Cost Management", "category": "Cloud", "targets": ["azure_costs.csv"], "how": "api",
     "env": ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"], "package": None,
     "settings": [{"key": "scope", "label": "Scope", "placeholder": "subscriptions/00000000-0000-0000-0000-000000000000"}],
     "permission": "Entra ID app with the 'Cost Management Reader' role on the subscription (read-only).",
     "steps": ["Register an app in Microsoft Entra ID and create a client secret.",
               "Give it the 'Cost Management Reader' role on the subscription or billing scope.",
               "Set AZURE_TENANT_ID, AZURE_CLIENT_ID and AZURE_CLIENT_SECRET in .env or the shell; enter the scope below.",
               "Pull. One Cost Details report per month; columns are those of a Cost Management export."],
     "docs": "https://learn.microsoft.com/azure/cost-management-billing/automate/usage-details-best-practices"},
    {"id": "openai", "name": "OpenAI usage and costs", "category": "AI", "targets": ["ai_usage.csv"], "how": "api",
     "env": ["OPENAI_ADMIN_KEY"], "package": None,
     "settings": [{"key": "project_departments", "label": "Department per project", "placeholder": "proj_abc=Marketing; proj_def=IT", "kind": "map"}],
     "permission": "Organization Admin API key (read usage and costs).",
     "steps": ["In the OpenAI platform, Organization settings > Admin keys: create an admin key.",
               "Set OPENAI_ADMIN_KEY in .env or the shell.",
               "Optional: map each project to a department below, so cost is allocated directly.",
               "Pull. Daily tokens by model and project; the project's cost is split over its models by tokens."],
     "docs": "https://platform.openai.com/docs/api-reference/usage"},
    {"id": "anthropic", "name": "Claude (Anthropic) usage and cost", "category": "AI", "targets": ["ai_usage.csv"], "how": "api",
     "env": ["ANTHROPIC_ADMIN_KEY"], "package": "anthropic",
     "settings": [{"key": "workspace_departments", "label": "Department per workspace", "placeholder": "wrkspc_01ab=Sales", "kind": "map"}],
     "permission": "Admin API key (sk-ant-admin...), reads the Usage and Cost Analytics API.",
     "steps": ["In the Claude Console, Settings > Admin keys: create an Admin API key (organization admins only).",
               "Set ANTHROPIC_ADMIN_KEY in .env or the shell.",
               "Install the optional packages: uv sync --group connectors (uses the official anthropic SDK).",
               "Pull. Daily tokens and cost by model and workspace, from 2026-01-01 and at most 365 days back."],
     "docs": "https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api"},
    {"id": "m365", "name": "Microsoft 365 licences", "category": "SaaS", "targets": ["saas_contracts.csv"], "how": "api",
     "env": ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"], "package": None,
     "settings": [{"key": "prices", "label": "CHF per licence and month", "placeholder": "SPE_E3=36; O365_BUSINESS_PREMIUM=20", "kind": "map"},
                  {"key": "contract_end", "label": "Contract end", "placeholder": "2027-06-30"},
                  {"key": "notice_period_days", "label": "Notice period (days)", "placeholder": "30"}],
     "permission": "Entra ID app with the Microsoft Graph application permission Organization.Read.All (read-only).",
     "steps": ["Use the same Entra ID app as for Azure, or a new one.",
               "Add the Graph application permission Organization.Read.All and grant admin consent.",
               "Enter the price per licence for each product below (Graph has no prices).",
               "Pull. Licences bought and assigned per product, for this month."],
     "docs": "https://learn.microsoft.com/graph/api/subscribedsku-list"},
    {"id": "saas_other", "name": "Other SaaS (Slack, Zoom, Atlassian, Salesforce, Google Workspace, ...)", "category": "SaaS",
     "targets": ["saas_contracts.csv", "ai_subscriptions.csv"], "how": "template", "env": [], "package": None, "settings": [],
     "permission": "None: an admin exports the licence list.",
     "steps": ["In each admin console, export the licence list (seats bought, seats active in the last 30 days).",
               "Copy them into the saas_contracts template (AI seats such as ChatGPT or Copilot: ai_subscriptions).",
               "Drop the filled file in step 2 above; the format check names any missing column."],
     "docs": ""},
]
BY_ID = {c["id"]: c for c in CONNECTORS}
PULLERS = {"aws_ce": providers.aws_ce, "azure_cost": providers.azure_cost, "openai": providers.openai,
           "anthropic": providers.anthropic, "m365": providers.m365}
# rows a pull replaces in an existing file: its own source, in the pulled period
SOURCE_KEY = {"openai": ("ai_usage.csv", "provider", "OpenAI"), "anthropic": ("ai_usage.csv", "provider", "Anthropic"),
              "m365": ("saas_contracts.csv", "provider", "Microsoft")}
DATE_COL = {"azure_costs.csv": "Date", "aws_costs.csv": "line_item_usage_start_date", "ai_usage.csv": "date",
            "saas_contracts.csv": "month"}


def catalog() -> list[dict]:
    """The connectors without any machine state, for data.js (the page lists them even when opened from disk)."""
    return [{**{k: c[k] for k in ("id", "name", "category", "targets", "how", "permission", "steps", "docs", "settings", "package")},
             "env": [{"name": n} for n in c["env"]] + [{"name": n, "alt": True} for n in c.get("env_alt", [])]} for c in CONNECTORS]


def _ws():
    from .. import workspace
    return workspace


def _cfg_path() -> Path:
    return _ws().folder() / "connectors.json"


def _log_path() -> Path:
    return _ws().folder() / "connectors_log.json"


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def _env_ok(c: dict, env=os.environ) -> tuple[bool, list[dict]]:
    vs = [{"name": n, "set": bool(env.get(n, "").strip())} for n in c["env"]]
    alt = [{"name": n, "set": bool(env.get(n, "").strip())} for n in c.get("env_alt", [])]
    ok = all(v["set"] for v in vs) or any(a["set"] for a in alt)
    return ok, vs + [{**a, "alt": True} for a in alt]


def status(env=os.environ) -> dict:
    cfg, log = _read(_cfg_path()), _read(_log_path())
    out = []
    for c in CONNECTORS:
        ok, vars_ = _env_ok(c, env)
        pkg = c["package"] is None or importlib.util.find_spec(c["package"]) is not None
        need = [s["key"] for s in c["settings"] if s.get("required", s["key"] == "scope")]
        conf = cfg.get(c["id"], {})
        missing_cfg = [k for k in need if not str(conf.get(k, "")).strip()]
        state = ("ready" if ok and pkg and not missing_cfg else "package" if not pkg else "credentials" if not ok else "settings") \
            if c["how"] == "api" else c["how"]
        out.append({**{k: c[k] for k in ("id", "name", "category", "targets", "how", "permission", "steps", "docs", "settings")},
                    "env": vars_, "package": c["package"], "package_ok": pkg, "config": conf, "missing_settings": missing_cfg,
                    "state": state, "last": log.get(c["id"])})
    return {"connectors": out, "period": default_period(), "workspace": str(_ws().folder().name)}


def default_period(today: dt.date | None = None) -> dict:
    """The workspace's baseline year if set, else the last 12 full months."""
    from ..config import read_settings
    s = read_settings(_ws().folder())
    t = today or dt.date.today()
    if s.get("baseline_start"):
        a = dt.date.fromisoformat(str(s["baseline_start"])[:10]).replace(day=1)
        b = a.replace(year=a.year + 1)
        return {"from": a.isoformat(), "to": min(b, t).isoformat()}
    end = t.replace(day=1)
    return {"from": end.replace(year=end.year - 1).isoformat(), "to": end.isoformat()}


def _parse_map(v) -> dict:
    """'a=1; b=2' or {'a': 1} -> {'a': '1', 'b': '2'}."""
    if isinstance(v, dict):
        return {str(k).strip(): str(x).strip() for k, x in v.items() if str(k).strip()}
    out = {}
    for part in str(v or "").replace("\n", ";").split(";"):
        if "=" in part:
            k, x = part.split("=", 1)
            if k.strip():
                out[k.strip()] = x.strip()
    return out


def set_config(cid: str, values: dict) -> dict:
    c = BY_ID[cid]                                     # KeyError for an unknown connector
    allowed = {s["key"]: s for s in c["settings"]}
    clean = {}
    for k, v in (values or {}).items():
        if k not in allowed:
            continue
        clean[k] = _parse_map(v) if allowed[k].get("kind") == "map" else str(v).strip()[:300]
    cfg = _read(_cfg_path())
    cfg[cid] = clean
    _cfg_path().parent.mkdir(parents=True, exist_ok=True)
    _cfg_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return status()


def _usd_chf() -> float:
    from ..config import SAMPLE_RAW
    for raw in (_ws().raw(), SAMPLE_RAW):
        p = raw / "exchange_rates.csv"
        if p.exists():
            fx = pd.read_csv(p, encoding="utf-8-sig")
            if len(fx) and "usd_chf" in fx:
                return float(fx.sort_values("month").usd_chf.iloc[-1])
    return 0.88


def _merge_write(name: str, new: pd.DataFrame, start: str, end: str, source: tuple | None, dest: Path) -> dict:
    """Write `new` into dest/name: rows of the same source in [start, end) are replaced, all other rows are kept."""
    p = inputs.path_for(dest, name)
    cols = inputs.BY_NAME[name]["columns"]
    kept = 0
    if p.exists():
        old = pd.read_csv(p, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        dc = DATE_COL[name]
        d = old[dc].str[:10] if dc in old else pd.Series("", index=old.index)
        in_period = (d >= start) & (d < end)
        same = (old[source[1]] == source[2]) if source and source[1] in old else pd.Series(True, index=old.index)
        old = old[~(in_period & same)]
        kept = len(old)
        new = pd.concat([old, new.astype(object)], ignore_index=True)
    for c in cols:
        if c not in new.columns:
            new[c] = ""
    new = new[cols + [c for c in new.columns if c not in cols]]
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    new.to_csv(buf, index=False)
    text = buf.getvalue()
    p.write_text(text, encoding="utf-8-sig")
    chk = inputs.check_text(text, name)
    return {"file": name, "rows": len(new), "kept": kept, "ok": chk["ok"], "missing": chk.get("missing", [])}


def _log(cid: str, entry: dict) -> None:
    log = _read(_log_path())
    log[cid] = entry
    _log_path().parent.mkdir(parents=True, exist_ok=True)
    _log_path().write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def pull(cid: str, start: str | None = None, end: str | None = None, dest: Path | None = None, **kw) -> dict:
    """Run one API connector and merge its rows into the workspace (or `dest`). Never raises for provider errors: the
    message comes back so the page can show it."""
    c = BY_ID[cid]
    if c["how"] != "api":
        raise ValueError(f"{c['name']} is not pulled from an API")
    per = default_period()
    start, end = start or per["from"], end or per["to"]
    dt.date.fromisoformat(start), dt.date.fromisoformat(end)              # ValueError on a bad date
    if start >= end:
        raise ValueError("the period is empty")
    dest = dest or _ws().raw()
    t0 = time.time()
    cfg = _read(_cfg_path()).get(cid, {})
    try:
        extra = {"usd_chf": _usd_chf()} if cid in ("openai", "anthropic") else {}
        res = PULLERS[cid](cfg, start, end, **extra, **kw)
        files = [_merge_write(n, df, start, end, SOURCE_KEY.get(cid), dest) for n, df in res["files"].items() if df is not None and len(df)]
        out = {"ok": True, "id": cid, "period": [start, end], "files": files, "report": res.get("report", {}),
               "seconds": round(time.time() - t0, 1)}
        if not files:
            out["report"]["warnings"] = out["report"].get("warnings", []) + ["The provider returned no rows for this period."]
    except KeyError as e:                          # a missing environment variable
        out = {"ok": False, "id": cid, "error": f"environment variable {e.args[0]} is not set"}
    except ModuleNotFoundError as e:
        out = {"ok": False, "id": cid, "error": f"package {e.name} missing: run uv sync --group connectors"}
    except AttributeError as e:                    # e.g. an anthropic SDK older than its Admin API endpoints
        out = {"ok": False, "id": cid, "error": f"the installed package is too old ({e}): run uv sync --group connectors --upgrade"}
    except Exception as e:                         # provider answered with an error: show it, never crash the server
        out = {"ok": False, "id": cid, "error": f"{type(e).__name__}: {str(e)[:400]}"}
    _log(cid, {**{k: out.get(k) for k in ("ok", "period", "error")}, "at": time.strftime("%Y-%m-%d %H:%M"),
               "rows": sum(f["rows"] for f in out.get("files", [])) if out.get("ok") else 0})
    return out


def import_focus(text: str, dest: Path | None = None) -> dict:
    res = focus.convert(text)                      # ValueError if it is not a FOCUS export
    dest = dest or _ws().raw()
    per = res["report"].get("period") or [None, None]
    start = per[0] or "1900-01-01"
    end = (dt.date.fromisoformat(per[1]) + dt.timedelta(days=1)).isoformat() if per[1] else "9999-12-31"
    files = [_merge_write(n, df, start, end, None, dest) for n, df in res["files"].items() if len(df)]
    out = {"ok": True, "id": "focus", "files": files, "report": res["report"]}
    _log("focus", {"ok": True, "period": per, "at": time.strftime("%Y-%m-%d %H:%M"), "rows": sum(f["rows"] for f in files)})
    return out
