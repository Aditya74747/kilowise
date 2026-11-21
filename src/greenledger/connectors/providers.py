"""Pull cost and usage from provider accounts and convert it into the exports Kilowise reads.

Every pull is read-only and runs on this machine (`greenledger serve` or `greenledger pull`). Credentials come only from
environment variables; nothing here stores, logs or returns a secret. Each function takes `http` (or `client`) so the
tests can replace the network with recorded answers.

  aws_ce        AWS Cost Explorer GetCostAndUsage (boto3; ce:GetCostAndUsage)            -> aws_costs.csv
  azure_cost    Azure Cost Management Cost Details report (REST, Entra ID app)          -> azure_costs.csv
  openai        OpenAI Usage API + Costs API (admin key)                                -> ai_usage.csv rows, provider OpenAI
  anthropic     Claude Usage and Cost Analytics API (official SDK, Admin API key)       -> ai_usage.csv rows, provider Anthropic
  m365          Microsoft Graph subscribedSkus (licences bought vs assigned)            -> saas_contracts.csv rows, provider Microsoft
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

from . import units

UA = "kilowise-connector/1.0"


def http_default(method: str, url: str, headers: dict | None = None, body: bytes | None = None, timeout: int = 120):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:              # return the error body: providers explain what is wrong there
        return e.code, dict(e.headers or {}), e.read()


def _json(status: int, body: bytes, what: str) -> dict:
    if status >= 400:
        msg = body.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{what}: HTTP {status} {msg}")
    return json.loads(body.decode("utf-8") or "{}")


def _days(start: str, end: str):
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    return s, e


def _chunks(start: str, end: str, days: int):
    s, e = _days(start, end)
    while s < e:
        n = min(e, s + dt.timedelta(days=days))
        yield s, n
        s = n


# ------------------------------------------------------------------------------------------------- AWS
def aws_ce(cfg: dict, start: str, end: str, client=None) -> dict:
    """Daily cost and usage by service and usage type. Usage types carry the region and the instance size
    ('EUC2-BoxUsage:m5.xlarge'), which units.normalise turns into vCPU-hours. Resource-level detail and tags need the
    AWS Data Export (FOCUS) instead: use the FOCUS connector for that."""
    if client is None:
        import boto3                                     # optional: uv sync --group connectors
        client = boto3.client("ce", region_name="us-east-1")   # Cost Explorer has one global endpoint in us-east-1
    rows, token = [], None
    while True:
        kw = dict(TimePeriod={"Start": start, "End": end}, Granularity="DAILY", Metrics=["UnblendedCost", "UsageQuantity"],
                  GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "USAGE_TYPE"}])
        if token:
            kw["NextPageToken"] = token
        r = client.get_cost_and_usage(**kw)
        for day in r.get("ResultsByTime", []):
            d = day["TimePeriod"]["Start"]
            for g in day.get("Groups", []):
                service, usage = g["Keys"][0], g["Keys"][1]
                cost = float(g["Metrics"]["UnblendedCost"]["Amount"])
                qty = float(g["Metrics"]["UsageQuantity"]["Amount"])
                unit = g["Metrics"]["UsageQuantity"].get("Unit", "")
                if abs(cost) < 1e-9 and abs(qty) < 1e-9:
                    continue
                if "BoxUsage" in usage or "SpotUsage" in usage:
                    unit = "Hrs"                          # instance usage is reported in hours
                u, q, _ = units.normalise("AWS", service, unit, qty, usage)
                rows.append({"line_item_usage_start_date": f"{d} 00:00:00", "line_item_resource_id": f"{service}/{usage}",
                             "product_servicecode": service, "product_region": units.aws_usage_region(usage),
                             "line_item_usage_amount": round(q, 6), "pricing_unit": u, "line_item_unblended_cost": cost,
                             "line_item_currency_code": g["Metrics"]["UnblendedCost"].get("Unit", "USD"),
                             "line_item_line_item_type": "Usage", "resource_tags_user_department": "",
                             "resource_tags_user_tool": service, "resource_tags_user_project": "",
                             "resource_tags_user_environment": "", "avg_cpu_utilization": "", "object_requests": "",
                             "line_item_description": usage})
        token = r.get("NextPageToken")
        if not token:
            break
    df = pd.DataFrame(rows)
    return {"files": {"aws_costs.csv": df}, "report": {"rows": len(df), "note": "Service and usage-type level; departments "
            "come from mapping_departments_tools.csv. For resource IDs and tags, export FOCUS and use the FOCUS file."}}


# ------------------------------------------------------------------------------------------------- Azure
def _entra_token(tenant: str, client_id: str, secret: str, scope: str, http) -> str:
    body = urllib.parse.urlencode({"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
                                   "scope": scope}).encode("utf-8")
    st, _, b = http("POST", f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                    {"Content-Type": "application/x-www-form-urlencoded"}, body)
    return _json(st, b, "Entra ID token")["access_token"]


def azure_cost(cfg: dict, start: str, end: str, http=http_default, env=os.environ, poll_s: float = 5) -> dict:
    """Cost Details report (the documented API for detailed cost data), one request per month: start the report, poll
    until it is ready, download the CSV blobs. Its columns are those of a Cost Management export."""
    scope = cfg.get("scope", "").strip().strip("/")
    if not scope:
        raise ValueError("set the scope, e.g. subscriptions/<subscription-id>")
    token = _entra_token(env["AZURE_TENANT_ID"], env["AZURE_CLIENT_ID"], env["AZURE_CLIENT_SECRET"],
                         "https://management.azure.com/.default", http)
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    frames = []
    for s, e in _chunks(start, end, 31):
        body = json.dumps({"metric": "ActualCost", "timePeriod": {"start": s.isoformat(), "end": (e - dt.timedelta(days=1)).isoformat()}}).encode()
        st, hd, b = http("POST", f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/"
                         "generateCostDetailsReport?api-version=2023-11-01", auth, body)
        if st >= 400:
            _json(st, b, "Cost Details report")
        loc = {k.lower(): v for k, v in hd.items()}.get("location")
        if not (st == 200 and b) and not (loc or "").startswith("https://management.azure.com/"):
            # the token is only ever sent to Azure Resource Manager, never to a host named in a response
            raise RuntimeError(f"Cost Details report: unexpected answer (HTTP {st}, no Azure status URL)")
        for _ in range(120):                           # up to about 10 minutes per month
            if st == 200 and b:
                break
            time.sleep(float({k.lower(): v for k, v in hd.items()}.get("retry-after", poll_s)) if poll_s else 0)
            st, hd, b = http("GET", loc, {"Authorization": f"Bearer {token}"}, None)
        if not (st == 200 and b):
            raise RuntimeError(f"Cost Details report for {s} not ready after 10 minutes (HTTP {st}); try again later")
        res = _json(st, b, "Cost Details status")
        for blob in (res.get("manifest") or {}).get("blobs", []):
            bst, _, data = http("GET", blob["blobLink"], {}, None)
            if bst >= 400:
                raise RuntimeError(f"Cost Details download: HTTP {bst}")
            frames.append(pd.read_csv(io.BytesIO(data), low_memory=False))
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    col = {c.lower(): c for c in raw.columns}
    g = lambda *names, default="": raw[col[next(n for n in names if n in col)]] if any(n in col for n in names) else pd.Series(default, index=raw.index)
    norm = [units.normalise("Azure", s, u, float(q or 0), f"{m} {mn}") for s, u, q, m, mn in
            zip(g("metercategory", "servicename"), g("unitofmeasure"), pd.to_numeric(g("quantity", default=0), errors="coerce").fillna(0),
                g("metersubcategory"), g("metername"))]
    df = pd.DataFrame({
        "Date": pd.to_datetime(g("date"), errors="coerce").dt.strftime("%Y-%m-%d"), "ResourceId": g("resourceid", "instancename"),
        "ServiceName": g("metercategory", "servicename"), "ResourceLocation": g("resourcelocation").astype(str).map(units.region_name),
        "Quantity": [round(n[1], 6) for n in norm], "UnitOfMeasure": [n[0] for n in norm],
        "CostInBillingCurrency": pd.to_numeric(g("costinbillingcurrency", "cost", default=0), errors="coerce"),
        "BillingCurrency": g("billingcurrency", "billingcurrencycode", default="CHF"), "ChargeType": g("chargetype", default="Usage"),
        "Tags": g("tags", default="{}").fillna("{}").astype(str).map(lambda t: t if t.strip().startswith("{") else "{" + t + "}"),
        "AvgCpuPercent": "", "Notes": ""}) if len(raw) else pd.DataFrame()
    return {"files": {"azure_costs.csv": df}, "report": {"rows": len(df), "months": len(list(_chunks(start, end, 31)))}}


# ------------------------------------------------------------------------------------------------- OpenAI
def openai(cfg: dict, start: str, end: str, http=http_default, env=os.environ, usd_chf: float = 0.88) -> dict:
    """OpenAI Usage API (completions, by model and project) and Costs API (by project). Project cost is split over its
    models by token share, because the Costs API does not break cost down by model."""
    key = env["OPENAI_ADMIN_KEY"]
    hdr = {"Authorization": f"Bearer {key}"}
    t0 = int(dt.datetime.combine(dt.date.fromisoformat(start), dt.time(), dt.timezone.utc).timestamp())
    t1 = int(dt.datetime.combine(dt.date.fromisoformat(end), dt.time(), dt.timezone.utc).timestamp())

    def pages(path: str, extra: str):
        page = None
        while True:
            url = f"https://api.openai.com/v1/organization/{path}?start_time={t0}&end_time={t1}&bucket_width=1d&limit=31{extra}"
            if page:
                url += f"&page={urllib.parse.quote(page)}"
            st, _, b = http("GET", url, hdr, None)
            j = _json(st, b, f"OpenAI {path}")
            yield from j.get("data", [])
            if not j.get("has_more"):
                break
            page = j.get("next_page")

    use = []
    for bucket in pages("usage/completions", "&group_by=model&group_by=project_id"):
        d = dt.datetime.fromtimestamp(bucket["start_time"], dt.timezone.utc).date().isoformat()
        for r in bucket.get("results", []):
            use.append({"date": d, "project": r.get("project_id") or "default", "model": r.get("model") or "unknown",
                        "requests": r.get("num_model_requests", 0), "tin": r.get("input_tokens", 0),
                        "tca": r.get("input_cached_tokens", 0), "tout": r.get("output_tokens", 0)})
    cost = {}
    for bucket in pages("costs", "&group_by=project_id"):
        d = dt.datetime.fromtimestamp(bucket["start_time"], dt.timezone.utc).date().isoformat()
        for r in bucket.get("results", []):
            amt = r.get("amount") or {}
            cost[(d, r.get("project_id") or "default")] = cost.get((d, r.get("project_id") or "default"), 0) + float(amt.get("value", 0))
    u = pd.DataFrame(use)
    if u.empty:
        return {"files": {"ai_usage.csv": _ai_frame([])}, "report": {"rows": 0}}
    u["tok"] = u.tin + u.tout
    share = u.tok / u.groupby(["date", "project"]).tok.transform("sum").replace(0, 1)
    u["cost_usd"] = [cost.get((d, p), 0) for d, p in zip(u.date, u.project)] * share
    dept = cfg.get("project_departments") or {}
    rows = [{"date": r.date, "resource_id": f"openai-{r.project}", "tool": f"OpenAI {r.project}", "department": dept.get(r.project, ""),
             "task_type": "", "model_class": _model_class(r.model), "provider": "OpenAI", "model": r.model,
             "requests": int(r.requests), "tokens_in": float(r.tin), "tokens_in_cache": float(r.tca), "tokens_out": float(r.tout),
             "cost_chf": round(r.cost_usd * usd_chf, 4), "project_id": ""} for r in u.itertuples()]
    return {"files": {"ai_usage.csv": _ai_frame(rows)}, "report": {"rows": len(rows), "usd_chf": usd_chf,
            "note": "Cost per model = the project's daily cost split by token share."}}


# ------------------------------------------------------------------------------------------------- Anthropic
ANTHROPIC_FLOOR = dt.date(2026, 1, 1)                  # the Usage and Cost Analytics API starts here, 365 days back


def anthropic(cfg: dict, start: str, end: str, client=None, env=os.environ, usd_chf: float = 0.88, today: dt.date | None = None) -> dict:
    """Claude Usage and Cost Analytics API through the official SDK (client.beta.organization.analytics): daily tokens
    and cost by model and workspace. Needs an Admin API key (sk-ant-admin...) in ANTHROPIC_ADMIN_KEY."""
    if client is None:
        import anthropic as sdk                          # optional: uv sync --group connectors
        client = sdk.Anthropic(api_key=env["ANTHROPIC_ADMIN_KEY"])
    today = today or dt.date.today()
    s, e = _days(start, end)
    floor = max(ANTHROPIC_FLOOR, today - dt.timedelta(days=364))
    warn = []
    if s < floor:
        warn.append(f"The API covers {floor} onwards; earlier days are left out.")
        s = floor
    use, cost = {}, {}
    for a, b in _chunks(s.isoformat(), e.isoformat(), 31):
        kw = dict(starting_at=f"{a}T00:00:00Z", ending_at=f"{b}T00:00:00Z", time_bucket_width="1d",
                  group_by=["model", "workspace_id"], limit=1000)
        for row in client.beta.organization.analytics.usage.list(**kw):
            k = (str(row.starting_at)[:10], row.group.model or "unknown", row.group.workspace_id or "default")
            us = row.usage
            cc = us.cache_creation
            cache_new = (getattr(cc, "ephemeral_1h_input_tokens", 0) or 0) + (getattr(cc, "ephemeral_5m_input_tokens", 0) or 0)
            use[k] = {"requests": us.requests or 0, "tca": us.cache_read_input_tokens or 0,
                      "tin": (us.uncached_input_tokens or 0) + cache_new + (us.cache_read_input_tokens or 0), "tout": us.output_tokens or 0}
        for row in client.beta.organization.analytics.cost.list(**kw):
            k = (str(row.starting_at)[:10], row.group.model or "unknown", row.group.workspace_id or "default")
            cost[k] = cost.get(k, 0) + float(row.cost.amount) / 100       # amount: decimal string in US cents
    dept = cfg.get("workspace_departments") or {}
    rows = []
    for k in sorted(set(use) | set(cost)):
        d, model, ws = k
        x = use.get(k, {"requests": 0, "tin": 0, "tca": 0, "tout": 0})
        rows.append({"date": d, "resource_id": f"anthropic-{ws}", "tool": f"Claude {ws}", "department": dept.get(ws, ""),
                     "task_type": "", "model_class": _model_class(model), "provider": "Anthropic", "model": model,
                     "requests": int(x["requests"]), "tokens_in": float(x["tin"]), "tokens_in_cache": float(x["tca"]),
                     "tokens_out": float(x["tout"]), "cost_chf": round(cost.get(k, 0) * usd_chf, 4), "project_id": ""})
    return {"files": {"ai_usage.csv": _ai_frame(rows)}, "report": {"rows": len(rows), "usd_chf": usd_chf, "warnings": warn}}


def _model_class(model: str) -> str:
    m = (model or "").lower()
    return "small" if any(x in m for x in ("mini", "nano", "haiku", "flash-lite", "small", "8b")) else "large"


AI_COLS = ["date", "resource_id", "tool", "department", "task_type", "model_class", "provider", "model", "requests",
           "tokens_in", "tokens_in_cache", "tokens_out", "cost_chf", "project_id"]


def _ai_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=AI_COLS)


# ------------------------------------------------------------------------------------------------- Microsoft 365
def m365(cfg: dict, start: str, end: str, http=http_default, env=os.environ, today: dt.date | None = None) -> dict:
    """Licences bought vs assigned per product (Graph subscribedSkus). Graph has no prices: enter CHF per licence and
    month in the connector settings. 'Assigned' is an upper bound for active use; the M8 saving is then conservative."""
    token = _entra_token(env["AZURE_TENANT_ID"], env["AZURE_CLIENT_ID"], env["AZURE_CLIENT_SECRET"],
                         "https://graph.microsoft.com/.default", http)
    st, _, b = http("GET", "https://graph.microsoft.com/v1.0/subscribedSkus", {"Authorization": f"Bearer {token}"}, None)
    skus = _json(st, b, "Graph subscribedSkus").get("value", [])
    prices = {k: float(v) for k, v in (cfg.get("prices") or {}).items() if str(v).strip()}
    month = (today or dt.date.today()).replace(day=1).isoformat()
    rows, unpriced = [], []
    for s in skus:
        bought = int((s.get("prepaidUnits") or {}).get("enabled", 0))
        if bought <= 0:
            continue
        name = s.get("skuPartNumber", "unknown")
        price = prices.get(name)
        if price is None:                                # without a price the cost would be unknown: leave it out, say so
            unpriced.append(name)
            continue
        rows.append({"month": month, "contract": name, "provider": "Microsoft", "cost_center": cfg.get("cost_center", ""),
                     "licences_purchased": bought, "licences_active_30d": int(s.get("consumedUnits", 0)),
                     "price_per_licence": price, "currency": "CHF",
                     "amount": round(bought * price, 2), "contract_status": "Final",
                     "contract_end": cfg.get("contract_end", ""), "notice_period_days": cfg.get("notice_period_days", ""),
                     "billing": cfg.get("billing", "monthly")})
    df = pd.DataFrame(rows, columns=["month", "contract", "provider", "cost_center", "licences_purchased", "licences_active_30d",
                                     "price_per_licence", "currency", "amount", "contract_status", "contract_end",
                                     "notice_period_days", "billing"])
    return {"files": {"saas_contracts.csv": df}, "report": {"rows": len(df), "unpriced": unpriced,
            "warnings": [f"Left out until a price is set: {', '.join(unpriced)}. Enter CHF per licence and month in the settings."]
            if unpriced else []}}
