"""Translate provider units, sizes and regions into what the ledger's energy model and grid factors understand.

The ledger (ledger._energy_azure_aws) knows vCPU-hour, vCore-hour, node-hour, GPU-hour, GB-day, GB, runner-minute and
capacity-day. Provider exports bill instance-hours of a named size (AWS 'BoxUsage:m5.xlarge', Azure 'D4s v5'),
storage in GB-months and transfer in GB. normalise() turns one row into the ledger's unit; anything it cannot
translate keeps its unit and is counted as 'no energy estimate' in the pull report, never silently.
"""
from __future__ import annotations

import re

# ---- regions: provider codes -> "Country (City)", the names factors.region_key() and the sample data use ----
REGIONS = {
    # AWS
    "eu-central-2": "Switzerland (Zurich)", "eu-central-1": "Germany (Frankfurt)", "eu-west-1": "Ireland (Dublin)",
    "eu-west-2": "United Kingdom (London)", "eu-west-3": "France (Paris)", "eu-north-1": "Sweden (Stockholm)",
    "eu-south-1": "Italy (Milan)", "eu-south-2": "Spain (Aragon)", "us-east-1": "United States (N. Virginia)",
    "us-east-2": "United States (Ohio)", "us-west-2": "United States (Oregon)",
    # Azure
    "switzerlandnorth": "Switzerland (Zurich)", "switzerlandwest": "Switzerland (Geneva)",
    "germanywestcentral": "Germany (Frankfurt)", "germanynorth": "Germany (Berlin)", "northeurope": "Ireland (Dublin)",
    "westeurope": "Netherlands (Amsterdam)", "francecentral": "France (Paris)", "swedencentral": "Sweden (Gävle)",
    "norwayeast": "Norway (Oslo)", "uksouth": "United Kingdom (London)", "italynorth": "Italy (Milan)",
    "spaincentral": "Spain (Madrid)", "polandcentral": "Poland (Warsaw)", "eastus": "United States (Virginia)",
    # Google Cloud
    "europe-west6": "Switzerland (Zurich)", "europe-west3": "Germany (Frankfurt)", "europe-west1": "Belgium (St. Ghislain)",
    "europe-west4": "Netherlands (Eemshaven)", "europe-north1": "Finland (Hamina)",
}
# AWS usage-type prefixes (Cost Explorer USAGE_TYPE dimension, e.g. "EUC2-BoxUsage:m5.xlarge")
AWS_USAGE_PREFIX = {"EUC1": "eu-central-1", "EUC2": "eu-central-2", "EU": "eu-west-1", "EUW1": "eu-west-1",
                    "EUW2": "eu-west-2", "EUW3": "eu-west-3", "EUN1": "eu-north-1", "EUS1": "eu-south-1",
                    "EUS2": "eu-south-2", "USE1": "us-east-1", "USE2": "us-east-2", "USW2": "us-west-2"}


def region_name(code_or_name: str | None) -> str:
    """'eu-central-2' / 'switzerlandnorth' / 'Switzerland North' -> 'Switzerland (Zurich)'; unknown stays as given."""
    s = (code_or_name or "").strip()
    key = s.lower().replace(" ", "")
    if key in REGIONS:
        return REGIONS[key]
    if s.lower() in REGIONS:
        return REGIONS[s.lower()]
    return s or "Unknown"


def aws_usage_region(usage_type: str) -> str:
    pre = (usage_type or "").split("-", 1)[0] if "-" in (usage_type or "") else ""
    return region_name(AWS_USAGE_PREFIX.get(pre, ""))


# ---- instance sizes -> vCPUs and GPUs ----
_AWS_SIZE = {"nano": 2, "micro": 2, "small": 2, "medium": 2, "large": 2, "xlarge": 4}
_AWS_GPU_FAMILY = {"p3": 1, "p4d": 8, "p4de": 8, "p5": 8, "p5e": 8, "g4dn": 1, "g4ad": 1, "g5": 1, "g6": 1, "g6e": 1}
_AWS_INSTANCE = re.compile(r"\b([a-z]\d+[a-z]*)\.(\d*)(nano|micro|small|medium|large|xlarge|metal)\b", re.I)
_AZ_SIZE = re.compile(r"\b(?:Standard_)?([A-Z]{1,3})(\d{1,3})([a-z_]*)\s?_?(v\d)?\b")


def aws_instance(text: str) -> tuple[int, int] | None:
    """'BoxUsage:m5.2xlarge' -> (8 vCPU, 0 GPU); 'g5.xlarge' -> (4, 1); None if no instance type is named."""
    m = _AWS_INSTANCE.search(text or "")
    if not m:
        return None
    fam, mult, size = m.group(1).lower(), m.group(2), m.group(3).lower()
    if size == "metal":
        vcpu = 96
    elif size == "xlarge":
        vcpu = 4 * (int(mult) if mult else 1)
    else:
        vcpu = _AWS_SIZE.get(size, 2)
    gpus = 0
    for f, n in _AWS_GPU_FAMILY.items():
        if fam == f:
            gpus = n if n > 1 else max(1, vcpu // 48)          # g5.48xlarge has 8 GPUs, smaller sizes one
    return vcpu, gpus


def azure_size(text: str) -> tuple[int, int] | None:
    """'D4s v5' / 'Standard_E8ds_v5' / 'NC24ads A100 v4' -> (vCPU, GPU). None if no VM size is named."""
    for m in _AZ_SIZE.finditer(text or ""):
        series, n = m.group(1).upper(), int(m.group(2))
        if series not in {"A", "B", "D", "DC", "E", "EC", "F", "FX", "L", "M", "H", "HB", "HC", "NC", "ND", "NV", "NP"}:
            continue
        gpus = 0
        if series.startswith("N"):
            gpus = 8 if series == "ND" and n >= 40 else max(1, n // 24) if n >= 24 else 1
        return n, gpus
    return None


# ---- units ----
def normalise(provider: str, service: str, unit: str, qty: float, hints: str = "") -> tuple[str, float, str]:
    """(ledger unit, quantity, note). provider 'Azure' or 'AWS'; hints = meter / usage type / SKU text."""
    u = (unit or "").strip().lower()
    text = f"{service} {hints}"
    hours = None
    if u in {"hrs", "hr", "hour", "hours", "1 hour", "instance-hours"} or re.fullmatch(r"\d+\s*hours?", u):
        mult = int(re.match(r"(\d+)", u).group(1)) if re.match(r"\d+", u) else 1
        hours = qty * mult
    if hours is not None:
        size = aws_instance(text) if provider == "AWS" else azure_size(text)
        if size:
            vcpu, gpus = size
            if gpus:
                return "GPU-hour", hours * gpus, f"{gpus} GPU per instance (size class)"
            return "vCPU-hour", hours * vcpu, f"{vcpu} vCPU per instance"
        return unit, qty, "hours of an unnamed size: no energy estimate"
    if u in {"gb-mo", "gb-month", "1 gb/month", "gb/month", "gib-mo", "gb-months", "1 gb/mo"} or "gb/month" in u:
        return "GB-day", qty * 30.4, "storage GB-months x 30.4 days"
    if u in {"gb", "1 gb", "gib", "1 gib"} and re.search(r"transfer|egress|bandwidth|out", text, re.I):
        return "GB", qty, "data transfer"
    if u in {"vcpu-hour", "vcore-hour", "node-hour", "gpu-hour", "gb-day", "gb", "runner-minute", "capacity-day", "month"}:
        canon = {"vcpu-hour": "vCPU-hour", "vcore-hour": "vCore-hour", "node-hour": "node-hour", "gpu-hour": "GPU-hour",
                 "gb-day": "GB-day", "gb": "GB", "runner-minute": "runner-minute", "capacity-day": "capacity-day",
                 "month": "month"}[u]
        return canon, qty, ""
    return unit, qty, "unit not in the energy model: cost counted, no energy estimate"


KNOWN_UNITS = {"vCPU-hour", "vCore-hour", "node-hour", "GPU-hour", "GB-day", "GB", "runner-minute", "capacity-day", "month"}
