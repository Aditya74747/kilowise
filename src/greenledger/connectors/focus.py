"""FinOps FOCUS cost exports (any cloud) -> the azure_costs.csv / aws_costs.csv formats the ledger reads.

FOCUS is the open billing standard that AWS (Data Exports, "FOCUS 1.0/1.2"), Microsoft (Cost Management exports,
"FOCUS cost") and Google Cloud (BigQuery FOCUS view) can export. Column names follow the FOCUS specification
(focus.finops.org, CC BY 4.0). Providers the ledger has no reader for yet (Google, Oracle, ...) are reported, not dropped
silently.
"""
from __future__ import annotations

import io
import json

import pandas as pd

from . import units

REQUIRED = ["ChargePeriodStart", "BilledCost", "BillingCurrency", "ServiceName"]
PROVIDER_COLS = ["ProviderName", "ServiceProviderName", "PublisherName", "InvoiceIssuerName"]


def _col(df: pd.DataFrame, *names: str, default=""):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(default, index=df.index)


def _tags(v) -> dict:
    if isinstance(v, dict):
        return v
    try:
        t = json.loads(v) if isinstance(v, str) and v.strip().startswith("{") else {}
        return t if isinstance(t, dict) else {}
    except ValueError:
        return {}


def _tag(t: dict, *keys: str) -> str:
    low = {str(k).lower(): v for k, v in t.items()}
    for k in keys:
        if k in low and low[k] not in (None, ""):
            return str(low[k])
    return ""


def convert(text: str) -> dict:
    """Returns {"files": {name: DataFrame}, "report": {...}}. Raises ValueError if it is not a FOCUS export."""
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"not a FOCUS export: columns {missing} missing")
    prov = _col(df, *PROVIDER_COLS).fillna("").astype(str)
    kind = prov.str.lower().map(lambda p: "AWS" if "amazon" in p or "aws" in p else "Azure" if "microsoft" in p or "azure" in p else "")
    tags = _col(df, "Tags").map(_tags)
    region = _col(df, "RegionId", "RegionName").fillna("").astype(str).map(units.region_name)
    hints = (_col(df, "SkuId").fillna("").astype(str) + " " + _col(df, "x_UsageType", "x_SkuMeterName", "SkuMeter").fillna("").astype(str)
             + " " + _col(df, "ChargeDescription", "SkuPriceDetails").fillna("").astype(str))
    qty = pd.to_numeric(_col(df, "ConsumedQuantity", "PricingQuantity", default=0), errors="coerce").fillna(0)
    unit = _col(df, "ConsumedUnit", "PricingUnit").fillna("").astype(str)
    service = _col(df, "ServiceName").fillna("").astype(str)
    norm = [units.normalise(k or "Azure", s, u, q, h) for k, s, u, q, h in zip(kind, service, unit, qty, hints)]
    out_unit = [n[0] for n in norm]
    out_qty = [round(n[1], 6) for n in norm]
    date = pd.to_datetime(df["ChargePeriodStart"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
    cost = pd.to_numeric(df["BilledCost"], errors="coerce").fillna(0)
    charge = _col(df, "ChargeCategory").fillna("Usage").astype(str)
    rid = _col(df, "ResourceId").fillna("").astype(str)
    rid = rid.where(rid != "", service + "/" + region)
    files, report = {}, {"rows_in": len(df), "by_provider": prov.replace("", "unknown").value_counts().to_dict()}

    az = kind == "Azure"
    if az.any():
        files["azure_costs.csv"] = pd.DataFrame({
            "Date": date[az], "ResourceId": rid[az], "ServiceName": service[az], "ResourceLocation": region[az],
            "Quantity": pd.Series(out_qty, index=df.index)[az], "UnitOfMeasure": pd.Series(out_unit, index=df.index)[az],
            "CostInBillingCurrency": cost[az], "BillingCurrency": df["BillingCurrency"][az], "ChargeType": charge[az],
            "Tags": tags[az].map(lambda t: json.dumps({"department": _tag(t, "department", "dept", "costcenter"),
                                                       "tool": _tag(t, "tool", "application", "app"),
                                                       "project": _tag(t, "project"), "environment": _tag(t, "environment", "env")},
                                                      ensure_ascii=False)),
            "AvgCpuPercent": "", "Notes": ""})
    aw = kind == "AWS"
    if aw.any():
        files["aws_costs.csv"] = pd.DataFrame({
            "line_item_usage_start_date": date[aw] + " 00:00:00", "line_item_resource_id": rid[aw],
            "product_servicecode": service[aw], "product_region": region[aw],
            "line_item_usage_amount": pd.Series(out_qty, index=df.index)[aw], "pricing_unit": pd.Series(out_unit, index=df.index)[aw],
            "line_item_unblended_cost": cost[aw], "line_item_currency_code": df["BillingCurrency"][aw],
            "line_item_line_item_type": charge[aw],
            "resource_tags_user_department": tags[aw].map(lambda t: _tag(t, "department", "user:department", "dept")),
            "resource_tags_user_tool": tags[aw].map(lambda t: _tag(t, "tool", "user:tool", "application")),
            "resource_tags_user_project": tags[aw].map(lambda t: _tag(t, "project", "user:project")),
            "resource_tags_user_environment": tags[aw].map(lambda t: _tag(t, "environment", "user:environment", "env")),
            "avg_cpu_utilization": "", "object_requests": "", "line_item_description": _col(df, "ChargeDescription").fillna("")[aw]})
    other = ~(az | aw)
    known = pd.Series([u in units.KNOWN_UNITS for u in out_unit], index=df.index)
    report.update(
        rows_azure=int(az.sum()), rows_aws=int(aw.sum()), rows_other=int(other.sum()),
        cost_other=round(float(cost[other].sum()), 2), other_providers=sorted(set(prov[other]) - {""}),
        rows_no_energy=int((~known & ~other).sum()), cost_no_energy=round(float(cost[~known & ~other].sum()), 2),
        currencies=sorted(set(df["BillingCurrency"].dropna().astype(str))),
        period=[str(date.min()), str(date.max())] if len(date.dropna()) else None)
    return {"files": files, "report": report}
