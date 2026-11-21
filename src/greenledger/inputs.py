"""The exports GreenLedger reads: one spec per file (where it goes, what it is, the columns the readers expect).

Used in three places: the app's "Your data" page (status + empty column templates for another company), the upload
check in `greenledger serve` (only these file names are accepted) and the workspace build. Extra columns are ignored;
a missing expected column is reported before anything is built.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

# (file, folder, group, label, what it is, expected columns). folder "core" = required, "extra" = optional bonus file.
SPECS: list[tuple[str, str, str, str, str, list[str]]] = [
    ("azure_costs.csv", "core", "Cloud", "Azure cost export", "Daily cost and usage per resource (Cost Management export)",
     ["Date", "ResourceId", "ServiceName", "ResourceLocation", "Quantity", "UnitOfMeasure", "CostInBillingCurrency",
      "BillingCurrency", "ChargeType", "Tags", "AvgCpuPercent", "Notes"]),
    ("aws_costs.csv", "core", "Cloud", "AWS cost and usage report", "CUR line items with tags and CPU %",
     ["line_item_usage_start_date", "line_item_resource_id", "product_servicecode", "product_region",
      "line_item_usage_amount", "pricing_unit", "line_item_unblended_cost", "line_item_currency_code",
      "line_item_line_item_type", "resource_tags_user_department", "resource_tags_user_tool",
      "resource_tags_user_project", "resource_tags_user_environment", "avg_cpu_utilization", "object_requests",
      "line_item_description"]),
    ("data_platform_usage.csv", "core", "Cloud", "Data platform usage", "Cluster node-hours and active hours per day",
     ["date", "resource_id", "cluster", "region", "node_count", "runtime_h", "active_use_h", "query_count"]),
    ("hoster_invoice.csv", "core", "Servers", "Hoster invoice", "Monthly invoice lines of the Swiss hoster",
     ["Date", "Item", "Service", "Quantity", "Unit", "Amount_CHF", "CostCenter", "ProjectNumber", "Accesses", "Remark"]),
    ("server_inventory.csv", "core", "Servers", "Server inventory", "One row per server: size, owner, criticality",
     ["server_id", "provider", "region", "vcpu", "ram_gb", "type", "owner_cost_center", "created", "last_login",
      "cpu_utilisation_30d_pct", "ram_utilisation_30d_pct", "runtime_h_30d", "tags", "operating_system",
      "patch_level", "project_id", "environment", "criticality"]),
    ("server_metrics_weekly.csv", "core", "Servers", "Server monitoring", "Weekly CPU, RAM, uptime and GPU use per server",
     ["week_start", "server_id", "cpu_avg_pct", "cpu_max_pct", "ram_avg_pct", "network_gb", "uptime_h", "gpu_avg_pct"]),
    ("ai_usage.csv", "core", "AI", "AI gateway log", "Daily requests and tokens per tool, task and model",
     ["date", "resource_id", "tool", "department", "task_type", "model_class", "provider", "model", "requests",
      "tokens_in", "tokens_in_cache", "tokens_out", "cost_chf", "project_id"]),
    ("ai_subscriptions.csv", "core", "AI", "AI subscriptions", "Monthly seats bought and used (ChatGPT, Copilot, ...)",
     ["month", "product", "provider", "cost_center", "licences_purchased", "licences_active_30d", "messages_30d",
      "price_per_seat", "currency", "amount", "contract_status", "contract_end", "notice_period_days", "billing"]),
    ("saas_contracts.csv", "core", "SaaS", "SaaS contracts", "Monthly licences bought and used, contract end, notice",
     ["month", "contract", "provider", "cost_center", "licences_purchased", "licences_active_30d", "price_per_licence",
      "currency", "amount", "contract_status", "contract_end", "notice_period_days", "billing"]),
    ("mapping_departments_tools.csv", "core", "Context", "Owners and departments",
     "Which department owns each resource, who decides, how critical it is",
     ["resource_id", "tool", "department", "cost_center", "responsible_role", "environment", "criticality",
      "default_project", "rechargeable"]),
    ("it_tickets.csv", "core", "Context", "IT tickets", "Tickets: protection windows and decisions are read from them",
     ["ticket_id", "date", "type", "resource_id", "title", "description", "status"]),
    ("business_calendar.csv", "core", "Context", "Business calendar", "Working days and public holidays",
     ["date", "weekday", "workday", "public_holiday", "company_holidays"]),
    ("exchange_rates.csv", "core", "Context", "Exchange rates", "Monthly EUR and USD to CHF",
     ["month", "eur_chf", "usd_chf"]),
    # optional bonus files: each adds a check, a finding or a measure; the build runs without them
    ("data_platform_jobs.csv", "extra", "Context", "Job scheduler", "Scheduled jobs: finds protection windows",
     ["date", "job_name", "resource_id", "start_time", "duration_h", "status", "triggered_by", "time_window"]),
    ("headcount.csv", "extra", "Context", "Headcount", "FTE per department: splits shared IT costs",
     ["month", "department", "fte"]),
    ("ai_agent_runs.jsonl", "extra", "AI", "AI agent runs", "One JSON object per agent run (retries, tokens)",
     ["run_id", "agent", "start", "retries", "usage"]),
    ("ai_invoice_monthly.csv", "extra", "AI", "AI provider invoice", "Monthly invoice: cross-check of the gateway",
     ["month", "provider", "model_class", "tokens_in", "tokens_out", "currency", "amount"]),
    ("provider_monthly_report.csv", "extra", "Cloud", "Provider monthly report", "Totals: cross-check of line items",
     ["month", "total_cost_chf", "label"]),
    ("data_center_locations.csv", "extra", "Cloud", "Data-centre locations", "Where each provider region is",
     ["provider", "region", "location", "used_by_sme"]),
    ("log_volume.csv", "extra", "Cloud", "Log volume", "Log GB per day and retention",
     ["date", "service", "log_gb", "unit", "retention_days", "project_id", "owner_cost_center"]),
    ("powerbi_usage.csv", "extra", "SaaS", "Power BI usage", "Report refreshes and views",
     ["date", "resource_id", "report", "department", "refresh_count", "refresh_duration_min", "view_count",
      "active_user_count", "report_type"]),
    ("ci_pipeline_runs.jsonl", "extra", "Cloud", "Build pipeline runs", "One JSON object per CI run",
     ["pipeline", "started_at", "status", "runner", "metrics"]),
    ("data_catalog_tables.csv", "extra", "Cloud", "Data catalogue", "Tables, size, last read, retention",
     ["table", "schema", "size_gb", "rows", "last_read", "last_written", "owner_cost_center", "project_id",
      "data_class", "retention_required"]),
    ("backup_chains.csv", "extra", "Servers", "Backup chains", "What is backed up where, how often",
     ["source", "category", "backup_tool", "size_gb", "frequency", "retention_days", "last_restore_test",
      "second_site", "criticality", "data_class", "cost_center"]),
    ("web_traffic.csv", "extra", "Cloud", "Web traffic", "Requests and egress per hour (note the sample rate)",
     ["time_utc", "requests", "gb_out", "bot_share_pct", "sample_rate", "status_5xx"]),
    ("m365_usage.csv", "extra", "SaaS", "Microsoft 365 usage", "Weekly active users and storage",
     ["week_start", "department", "cost_center", "active_users", "storage", "teams_video_minutes", "mails_sent",
      "storage_unit"]),
    ("projects.csv", "extra", "Context", "Projects", "Project names and whether they can be recharged",
     ["project_id", "project_name", "type", "customer", "cost_center", "start", "end", "rechargeable", "status"]),
    ("project_hours_monthly.csv", "extra", "Context", "Project hours", "Hours per project: alternative allocation key",
     ["month", "project_id", "department", "hours"]),
]
FIELDS = ("file", "folder", "group", "label", "what", "columns")
BY_NAME = {s[0]: dict(zip(FIELDS, s)) for s in SPECS}
MAX_BYTES = 200 * 1024 * 1024
BOM, NL = chr(0xFEFF), chr(10)


def path_for(raw: Path, name: str) -> Path:
    """Where a known file lives inside a raw folder. Unknown names raise: uploads can only write these files."""
    spec = BY_NAME[name]
    return (raw / "extra" / name) if spec["folder"] == "extra" else (raw / name)


def header_of(text: str, name: str) -> list[str]:
    if name.endswith(".jsonl"):
        for line in text.splitlines():
            if line.strip():
                obj = json.loads(line)
                return list(obj) if isinstance(obj, dict) else []
        return []
    first = text.lstrip(BOM).splitlines()[:1]
    if not first:
        return []
    delim = ";" if first[0].count(";") > first[0].count(",") else ","
    return [c.strip() for c in next(csv.reader(io.StringIO(first[0]), delimiter=delim))]


def check_text(text: str, name: str) -> dict:
    """Format check of one export (before any build): known name, expected columns, rows."""
    spec = BY_NAME.get(name)
    if not spec:
        return {"file": name, "ok": False, "error": "unknown file name", "missing": [], "rows": 0}
    try:
        cols = header_of(text, name)
    except (ValueError, csv.Error) as e:
        return {"file": name, "ok": False, "error": f"cannot read the file: {e}", "missing": [], "rows": 0}
    missing = [c for c in spec["columns"] if c not in cols]
    if name.endswith(".jsonl"):
        rows = sum(1 for line in text.splitlines() if line.strip())
    else:                                          # csv reader: quoted line breaks in free text stay one row
        first = text.lstrip(BOM).partition(NL)[0]
        delim = ";" if first.count(";") > first.count(",") else ","
        rows = max(0, sum(1 for r in csv.reader(io.StringIO(text.lstrip(BOM)), delimiter=delim) if r) - 1)
    return {"file": name, "ok": not missing and rows > 0, "missing": missing, "rows": rows,
            "extra": [c for c in cols if c not in spec["columns"]],
            "error": "" if rows else "no data rows"}


def check_file(path: Path) -> dict:
    return check_text(path.read_text(encoding="utf-8-sig", errors="replace"), path.name)


def status(raw: Path, dq: list[dict]) -> list[dict]:
    """Per expected file: present, rows, format check and the cleaning steps applied (for the app)."""
    out = []
    for name, spec in BY_NAME.items():
        p = path_for(raw, name)
        fixes = [e for e in dq if e.get("source") in (name, f"extra/{name}")]
        row = {k: spec[k] for k in ("file", "folder", "group", "label", "what", "columns")}
        row["present"] = p.exists()
        if p.exists():
            chk = check_file(p)
            row.update(rows=chk["rows"], ok=chk["ok"], missing=chk["missing"])
        row["fixes"] = len(fixes)
        row["warn"] = sum(1 for e in fixes if e.get("severity") == "warn")
        out.append(row)
    return out


def missing_required(raw: Path) -> list[str]:
    return [n for n, s in BY_NAME.items() if s["folder"] == "core" and not path_for(raw, n).exists()]


def write_templates(folder: Path) -> None:
    """Empty column templates (header row only) so another company can prepare its exports in the same format."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, spec in BY_NAME.items():
        if name.endswith(".jsonl"):
            body = json.dumps({c: None for c in spec["columns"]}) + "\n"
        else:
            body = ",".join(spec["columns"]) + "\n"
        (folder / name).write_text(body, encoding="utf-8")
