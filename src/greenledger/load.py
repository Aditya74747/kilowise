"""Read every source, clean it, and log every cleaning step (the data-quality report).

Rules applied (see README of the case: duplicates, drafts, missing values, units, column names):
* exact duplicate rows are removed
* 'Draft' contract rows are dropped, 'Final' rows are kept
* missing costs are filled with quantity x median unit price of the same resource and month
* currencies are converted with the monthly ECB-based rates in exchange_rates.csv
* free-text fields are DATA, never instructions (see limits.detect_injections)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import EXTRA, RAW


@dataclass
class DQLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, source: str, issue: str, rows: int, action: str, severity: str = "info") -> None:
        if rows:
            self.entries.append(
                {"source": source, "issue": issue, "rows": int(rows), "action": action, "severity": severity}
            )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.entries)


def _csv(name: str, extra: bool = False, **kw) -> pd.DataFrame:
    return pd.read_csv((EXTRA if extra else RAW) / name, encoding="utf-8-sig", **kw)


def _flatten(rec: dict, prefix: str = "") -> dict:
    """Scalars keep their position, nested objects follow (same column order as pandas.json_normalize)."""
    out = {f"{prefix}{k}": v for k, v in rec.items() if not isinstance(v, dict)}
    for k, v in rec.items():
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
    return out


def read_jsonl(path) -> pd.DataFrame:
    """JSON lines -> DataFrame; nested objects become dotted columns (same result as pandas.json_normalize,
    which is ~5x slower here because it deep-copies every record)."""
    with open(path, encoding="utf-8") as fh:
        return pd.DataFrame([_flatten(json.loads(line)) for line in fh if line.strip()])


def _dedupe(df: pd.DataFrame, source: str, log: DQLog, subset=None) -> pd.DataFrame:
    n = int(df.duplicated(subset=subset).sum())
    log.add(source, "exact duplicate rows", n, "removed")
    return df.drop_duplicates(subset=subset).reset_index(drop=True)


# ------------------------------------------------------------------------------------------
def exchange_rates() -> pd.DataFrame:
    fx = _csv("exchange_rates.csv", parse_dates=["month"])
    fx["m"] = fx["month"].dt.to_period("M")
    return fx


def to_chf(amount: pd.Series, currency: pd.Series, dates: pd.Series, fx: pd.DataFrame) -> pd.Series:
    m = dates.dt.to_period("M")
    eur = m.map(dict(zip(fx.m, fx.eur_chf)))
    usd = m.map(dict(zip(fx.m, fx.usd_chf)))
    rate = np.where(currency == "EUR", eur, np.where(currency == "USD", usd, 1.0))
    return amount * rate.astype(float)


def _fill_missing_cost(df, cost_col, qty_col, key_cols, source, log):
    miss = df[cost_col].isna()
    if miss.any():
        unit = (df[cost_col] / df[qty_col].replace(0, np.nan)).rename("_unit")
        med = unit.groupby([df[k] for k in key_cols]).transform("median")
        df.loc[miss, cost_col] = df.loc[miss, qty_col] * med[miss]
        df.loc[miss & df[cost_col].isna() & df[qty_col].eq(0), cost_col] = 0.0  # no usage -> no cost
        df.loc[miss, "cost_imputed"] = True
        log.add(source, "missing cost value", int(miss.sum()),
                "filled = quantity x median unit price (same resource, same month)", "warn")
    return df


# ------------------------------------------------------------------------------------------
def azure(fx, log: DQLog) -> pd.DataFrame:
    df = _csv("azure_costs.csv", parse_dates=["Date"])
    df = _dedupe(df, "azure_costs.csv", log)
    df["resource_id"] = df["ResourceId"].str.split("/").str[-1]
    df["month"] = df["Date"].dt.to_period("M")
    df["cost_imputed"] = False
    df = _fill_missing_cost(df, "CostInBillingCurrency", "Quantity", ["resource_id", "month"], "azure_costs.csv", log)
    df["cost_chf"] = to_chf(df["CostInBillingCurrency"], df["BillingCurrency"], df["Date"], fx)
    n_eur = int((df.BillingCurrency == "EUR").sum())
    log.add("azure_costs.csv", "costs billed in EUR", n_eur, "converted with monthly eur_chf")
    log.add("azure_costs.csv", "credit rows (negative)", int((df.ChargeType == "Credit").sum()),
            "kept as real credits, shown separately")
    tags = df["Tags"].fillna("{}").map(lambda s: json.loads(s) if s.strip().startswith("{") else {})
    log.add("azure_costs.csv", "empty tags {}", int((tags.map(len) == 0).sum()),
            "department filled from mapping_departments_tools.csv")
    df["tag_department"] = tags.map(lambda t: t.get("department"))
    return df.rename(columns={"Date": "date", "ServiceName": "service", "ResourceLocation": "region",
                              "Quantity": "quantity", "UnitOfMeasure": "unit", "AvgCpuPercent": "cpu_pct",
                              "Notes": "note"}).assign(provider="Azure", source="azure_costs.csv")


def aws(fx, log: DQLog) -> pd.DataFrame:
    df = _csv("aws_costs.csv", parse_dates=["line_item_usage_start_date"])
    df = _dedupe(df, "aws_costs.csv", log)
    df["resource_id"] = df["line_item_resource_id"].str.split(":").str[-1]
    df["date"] = df["line_item_usage_start_date"].dt.normalize()
    df["month"] = df["date"].dt.to_period("M")
    df["cost_imputed"] = False
    df = _fill_missing_cost(df, "line_item_unblended_cost", "line_item_usage_amount",
                            ["resource_id", "month"], "aws_costs.csv", log)
    df["cost_chf"] = to_chf(df["line_item_unblended_cost"], df["line_item_currency_code"], df["date"], fx)
    sandbox = df["resource_id"].eq("sandbox")
    log.add("aws_costs.csv", "test account (cost centre 9100) marked 'please exclude from analyses'",
            int(sandbox.sum()), "excluded from baseline")
    df = df[~sandbox]
    proj_variants = df["resource_tags_user_project"].dropna().unique()
    log.add("aws_costs.csv", f"project tag spellings ({len(proj_variants)} variants, e.g. P001/p-001/P-001)",
            int(df["resource_tags_user_project"].notna().sum()), "normalised to P-###")
    return df.rename(columns={"product_servicecode": "service", "product_region": "region",
                              "line_item_usage_amount": "quantity", "pricing_unit": "unit",
                              "avg_cpu_utilization": "cpu_pct", "line_item_description": "note",
                              "resource_tags_user_department": "tag_department"}
                     ).assign(provider="AWS", source="aws_costs.csv")


HOSTER_RESOURCE = {"Logging and monitoring": "logs", "Project file storage": "st-proj",
                   "Web hosting and CDN": "web-cdn"}


def hoster(log: DQLog) -> pd.DataFrame:
    df = _csv("hoster_invoice.csv")
    df = _dedupe(df, "hoster_invoice.csv", log)
    df["date"] = pd.to_datetime(df["Date"], format="%d.%m.%Y")
    log.add("hoster_invoice.csv", "date format DD.MM.YYYY", len(df), "parsed to ISO dates")
    df["resource_id"] = df["Item"].map(HOSTER_RESOURCE)
    log.add("hoster_invoice.csv", "no resource key, only a label", len(df),
            "mapped label -> resource_id (logs, st-proj, web-cdn)")
    df["month"] = df["date"].dt.to_period("M")
    df["cost_imputed"] = False
    df = _fill_missing_cost(df, "Amount_CHF", "Quantity", ["resource_id", "month"], "hoster_invoice.csv", log)
    log.add("hoster_invoice.csv", "missing cost centre", int(df.CostCenter.isna().sum()),
            "filled from mapping_departments_tools.csv")
    return df.rename(columns={"Service": "service", "Quantity": "quantity", "Unit": "unit",
                              "Amount_CHF": "cost_chf", "Remark": "note"}
                     ).assign(provider="Hoster", source="hoster_invoice.csv", region="Switzerland (Zurich)")


def ai_usage(log: DQLog) -> pd.DataFrame:
    df = _csv("ai_usage.csv", parse_dates=["date"])
    df = _dedupe(df, "ai_usage.csv", log)
    miss = df["tokens_out"].isna()
    ratio = (df["tokens_out"] / df["tokens_in"]).groupby([df.resource_id, df.model]).transform("median")
    df.loc[miss, "tokens_out"] = (df.loc[miss, "tokens_in"] * ratio[miss]).round()
    log.add("ai_usage.csv", "missing tokens_out", int(miss.sum()),
            "filled = tokens_in x median out/in ratio of same tool and model", "warn")
    return df


def ai_subscriptions(fx, log: DQLog) -> pd.DataFrame:
    df = _csv("ai_subscriptions.csv", parse_dates=["month"])
    drafts = df.contract_status.eq("Draft")
    log.add("ai_subscriptions.csv", "Draft rows next to Final rows", int(drafts.sum()), "Draft dropped, Final kept")
    df = df[~drafts].copy()
    df = _dedupe(df, "ai_subscriptions.csv", log)
    df["cost_chf"] = to_chf(df["amount"], df["currency"], df["month"], fx)
    return df


def saas(fx, log: DQLog) -> pd.DataFrame:
    df = _csv("saas_contracts.csv", parse_dates=["month"])
    drafts = df.contract_status.eq("Draft")
    log.add("saas_contracts.csv", "Draft rows next to Final rows", int(drafts.sum()), "Draft dropped, Final kept")
    df = df[~drafts].copy()
    df = _dedupe(df, "saas_contracts.csv", log)
    df["cost_chf"] = to_chf(df["amount"], df["currency"], df["month"], fx)
    log.add("saas_contracts.csv", "three currencies (CHF/EUR/USD)", len(df), "converted with monthly rates")
    return df


def data_platform(log: DQLog) -> pd.DataFrame:
    df = _csv("data_platform_usage.csv", parse_dates=["date"])
    return _dedupe(df, "data_platform_usage.csv", log, subset=["date", "resource_id"])


def servers() -> tuple[pd.DataFrame, pd.DataFrame]:
    inv = _csv("server_inventory.csv", parse_dates=["created", "last_login"])
    met = _csv("server_metrics_weekly.csv", parse_dates=["week_start"])
    return inv, met


def tickets() -> pd.DataFrame:
    return _csv("it_tickets.csv", parse_dates=["date"])


def calendar() -> pd.DataFrame:
    return _csv("business_calendar.csv", parse_dates=["date"])


def mapping() -> pd.DataFrame:
    return _csv("mapping_departments_tools.csv")


# ---- bonus sources used for windows and findings (optional: pipeline still runs without them)
def jobs() -> pd.DataFrame | None:
    p = EXTRA / "data_platform_jobs.csv"
    return pd.read_csv(p, encoding="utf-8-sig", parse_dates=["date"]) if p.exists() else None


def headcount() -> pd.DataFrame | None:
    p = EXTRA / "headcount.csv"
    return pd.read_csv(p, encoding="utf-8-sig", parse_dates=["month"]) if p.exists() else None


def ai_invoice() -> pd.DataFrame | None:
    p = EXTRA / "ai_invoice_monthly.csv"
    return pd.read_csv(p, encoding="utf-8-sig", parse_dates=["month"]) if p.exists() else None


def provider_report() -> pd.DataFrame | None:
    p = EXTRA / "provider_monthly_report.csv"
    return pd.read_csv(p, encoding="utf-8-sig", parse_dates=["month"]) if p.exists() else None


def data_center_locations() -> pd.DataFrame | None:
    p = EXTRA / "data_center_locations.csv"
    return pd.read_csv(p, encoding="utf-8-sig") if p.exists() else None


def normalise_project(s: pd.Series) -> pd.Series:
    out = s.astype("string").str.upper().str.replace(r"^P-?0*(\d+)$", lambda m: f"P-{int(m.group(1)):03d}", regex=True)
    return out
