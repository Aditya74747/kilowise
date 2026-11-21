"""Connectors (Data sources > Connect your accounts): every provider answer is converted into a valid export, pulls
merge by source and period, units and regions reach the energy model, and no secret ever leaves the machine."""
import json
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from greenledger import connectors, inputs
from greenledger.connectors import focus, providers, units


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("GL_UPLOAD_WORKSPACE", str(tmp_path))
    return tmp_path


def _valid(path, name):
    chk = inputs.check_file(path)
    assert chk["ok"], chk
    return pd.read_csv(path, encoding="utf-8-sig")


# ---------------------------------------------------------------- units and regions
def test_sizes_units_and_regions_reach_the_energy_model():
    assert units.aws_instance("EUC2-BoxUsage:m5.2xlarge") == (8, 0)
    assert units.aws_instance("p4d.24xlarge")[1] == 8
    assert units.azure_size("Standard_D4s_v5") == (4, 0) and units.azure_size("D8ds v5")[0] == 8
    assert units.normalise("AWS", "EC2", "Hrs", 10, "BoxUsage:m5.xlarge")[:2] == ("vCPU-hour", 40)
    assert units.normalise("Azure", "Virtual Machines", "100 Hours", 1, "D4s v5")[:2] == ("vCPU-hour", 400)
    assert units.normalise("AWS", "S3", "GB-Mo", 1, "")[:2] == ("GB-day", 30.4)
    assert units.normalise("AWS", "Data Transfer", "GB", 5, "DataTransfer-Out-Bytes")[:2] == ("GB", 5)
    assert units.normalise("AWS", "Support", "Request", 1, "")[2]                     # unknown: said, not hidden
    assert units.region_name("eu-central-2") == units.region_name("switzerlandnorth") == "Switzerland (Zurich)"
    assert units.aws_usage_region("EUC1-BoxUsage:t3.large") == "Germany (Frankfurt)"


# ---------------------------------------------------------------- FOCUS
FOCUS_CSV = """ChargePeriodStart,ChargePeriodEnd,BilledCost,BillingCurrency,ProviderName,ServiceName,RegionId,ResourceId,ConsumedQuantity,ConsumedUnit,SkuId,ChargeCategory,Tags
2026-03-01T00:00:00Z,2026-03-02T00:00:00Z,12.5,EUR,Microsoft,Virtual Machines,switzerlandnorth,/subscriptions/1/vm-a,24,1 Hour,D4s v5,Usage,"{""department"": ""IT"", ""app"": ""ERP""}"
2026-03-01T00:00:00Z,2026-03-02T00:00:00Z,3.2,USD,Amazon Web Services,Amazon EC2,eu-central-1,i-0abc,24,Hrs,BoxUsage:m5.xlarge,Usage,"{""user:department"": ""Sales""}"
2026-03-01T00:00:00Z,2026-03-02T00:00:00Z,0.4,USD,Amazon Web Services,Amazon S3,eu-west-1,bucket-1,2,GB-Mo,TimedStorage-ByteHrs,Usage,{}
2026-03-01T00:00:00Z,2026-03-02T00:00:00Z,7.0,USD,Google Cloud,Compute Engine,europe-west6,vm-g,24,hour,n2-standard-4,Usage,{}
"""


def test_focus_export_becomes_azure_and_aws_files(ws):
    r = connectors.import_focus(FOCUS_CSV)
    assert {f["file"] for f in r["files"]} == {"azure_costs.csv", "aws_costs.csv"} and all(f["ok"] for f in r["files"])
    az = _valid(inputs.path_for(ws / "raw", "azure_costs.csv"), "azure_costs.csv")
    assert az.UnitOfMeasure[0] == "vCPU-hour" and az.Quantity[0] == 96 and az.ResourceLocation[0] == "Switzerland (Zurich)"
    assert json.loads(az.Tags[0])["department"] == "IT" and json.loads(az.Tags[0])["tool"] == "ERP"
    aw = _valid(inputs.path_for(ws / "raw", "aws_costs.csv"), "aws_costs.csv")
    assert set(aw.pricing_unit) == {"vCPU-hour", "GB-day"} and aw.product_region[0] == "Germany (Frankfurt)"
    assert aw.resource_tags_user_department[0] == "Sales"
    assert r["report"]["rows_other"] == 1 and r["report"]["other_providers"] == ["Google Cloud"]   # reported, not dropped
    with pytest.raises(ValueError):
        focus.convert("a,b\n1,2\n")


# ---------------------------------------------------------------- AWS Cost Explorer
class FakeCE:
    def __init__(self):
        self.calls = 0

    def get_cost_and_usage(self, **kw):
        self.calls += 1
        g = lambda svc, ut, cost, q, unit: {"Keys": [svc, ut], "Metrics": {"UnblendedCost": {"Amount": str(cost), "Unit": "USD"},
                                                                         "UsageQuantity": {"Amount": str(q), "Unit": unit}}}
        if "NextPageToken" not in kw:
            return {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01"}, "Groups": [g("Amazon EC2", "EUC2-BoxUsage:m5.xlarge", 4.6, 24, "Hrs")]}],
                    "NextPageToken": "p2"}
        return {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-02"}, "Groups": [g("Amazon S3", "EU-TimedStorage-ByteHrs", 0.2, 3, "GB-Mo"),
                                                                                    g("Tax", "Tax", 0, 0, "")]}]}


def test_aws_cost_explorer_pages_and_sizes(ws):
    ce = FakeCE()
    r = connectors.pull("aws_ce", "2026-03-01", "2026-03-03", client=ce)
    assert r["ok"] and ce.calls == 2
    aw = _valid(inputs.path_for(ws / "raw", "aws_costs.csv"), "aws_costs.csv")
    assert len(aw) == 2                                           # the empty Tax row is skipped
    ec2 = aw[aw.product_servicecode == "Amazon EC2"].iloc[0]
    assert ec2.pricing_unit == "vCPU-hour" and ec2.line_item_usage_amount == 96 and ec2.product_region == "Switzerland (Zurich)"


# ---------------------------------------------------------------- Azure Cost Details
def test_azure_cost_details_report(ws, monkeypatch):
    for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.setenv(k, "x")
    blob = ("date,resourceId,meterCategory,meterSubCategory,meterName,resourceLocation,quantity,unitOfMeasure,"
            "costInBillingCurrency,billingCurrency,chargeType,tags\n"
            "03/01/2026,/subscriptions/1/vm-a,Virtual Machines,Dsv5 Series,D4s v5,SwitzerlandNorth,24,1 Hour,12.5,CHF,Usage,"
            "\"\"\"department\"\": \"\"IT\"\"\"\n")
    seen = []

    def http(method, url, headers=None, body=None, timeout=120):
        seen.append((method, url))
        if "login.microsoftonline.com" in url:
            return 200, {}, json.dumps({"access_token": "tok"}).encode()
        if "generateCostDetailsReport" in url:
            return 202, {"Location": "https://management.azure.com/op/1", "Retry-After": "0"}, b""
        if url.endswith("/op/1"):
            return 200, {}, json.dumps({"manifest": {"blobs": [{"blobLink": "https://blob/1.csv"}]}}).encode()
        if url == "https://blob/1.csv":
            return 200, {}, blob.encode()
        raise AssertionError(url)

    connectors.set_config("azure_cost", {"scope": "subscriptions/1"})
    r = connectors.pull("azure_cost", "2026-03-01", "2026-03-02", http=http, poll_s=0)
    assert r["ok"], r
    az = _valid(inputs.path_for(ws / "raw", "azure_costs.csv"), "azure_costs.csv")
    assert az.UnitOfMeasure[0] == "vCPU-hour" and az.ResourceLocation[0] == "Switzerland (Zurich)" and az.Date[0] == "2026-03-01"
    assert json.loads(az.Tags[0])["department"] == "IT"
    assert all("management.azure.com" in u or "login" in u or "blob" in u for _, u in seen)


# ---------------------------------------------------------------- OpenAI and Anthropic share ai_usage.csv
def _openai_http(method, url, headers=None, body=None, timeout=120):
    assert headers["Authorization"] == "Bearer sk-admin-test"
    if "usage/completions" in url:
        return 200, {}, json.dumps({"data": [{"start_time": 1772323200, "results": [
            {"model": "gpt-5.4", "project_id": "proj_a", "num_model_requests": 10, "input_tokens": 9000,
             "input_cached_tokens": 1000, "output_tokens": 1000},
            {"model": "gpt-5.4-mini", "project_id": "proj_a", "num_model_requests": 5, "input_tokens": 9000,
             "input_cached_tokens": 0, "output_tokens": 1000}]}], "has_more": False}).encode()
    if "/costs" in url:
        return 200, {}, json.dumps({"data": [{"start_time": 1772323200, "results": [
            {"amount": {"value": 2.0, "currency": "usd"}, "project_id": "proj_a"}]}], "has_more": False}).encode()
    raise AssertionError(url)


def _anthropic_client():
    usage = NS(uncached_input_tokens=5000, cache_creation=NS(ephemeral_1h_input_tokens=0, ephemeral_5m_input_tokens=1000),
               cache_read_input_tokens=4000, output_tokens=2000, requests=7)
    urow = NS(starting_at="2026-03-01T00:00:00Z", group=NS(model="claude-sonnet-5-5", workspace_id="wrkspc_1"), usage=usage)
    crow = NS(starting_at="2026-03-01T00:00:00Z", group=NS(model="claude-sonnet-5-5", workspace_id="wrkspc_1"),
              cost=NS(amount="150.000000", currency="USD"))
    calls = []
    lister = lambda rows: NS(list=lambda **kw: (calls.append(kw), rows)[1])
    return NS(beta=NS(organization=NS(analytics=NS(usage=lister([urow]), cost=lister([crow]))))), calls


def test_openai_and_anthropic_merge_by_source_and_period(ws, monkeypatch):
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-test")
    connectors.set_config("openai", {"project_departments": "proj_a=Marketing"})
    r = connectors.pull("openai", "2026-03-01", "2026-03-02", http=_openai_http)
    assert r["ok"], r
    client, calls = _anthropic_client()
    connectors.set_config("anthropic", {"workspace_departments": {"wrkspc_1": "Sales"}})
    r2 = connectors.pull("anthropic", "2026-03-01", "2026-03-02", client=client, today=pd.Timestamp("2026-09-01").date())
    assert r2["ok"], r2
    assert calls[0]["group_by"] == ["model", "workspace_id"] and calls[0]["time_bucket_width"] == "1d"
    ai = _valid(inputs.path_for(ws / "raw", "ai_usage.csv"), "ai_usage.csv")
    assert set(ai.provider) == {"OpenAI", "Anthropic"} and len(ai) == 3
    oa = ai[ai.provider == "OpenAI"]
    assert oa.department.eq("Marketing").all() and oa.model_class.tolist() == ["large", "small"]
    assert oa.cost_chf.sum() == pytest.approx(2.0 * connectors._usd_chf(), rel=1e-3)      # project cost split by tokens
    an = ai[ai.provider == "Anthropic"].iloc[0]
    assert an.tokens_in == 10000 and an.tokens_in_cache == 4000 and an.department == "Sales"
    assert an.cost_chf == pytest.approx(1.5 * connectors._usd_chf(), rel=1e-3)             # amount is in cents
    # pulling OpenAI again for the same day replaces only its own rows
    connectors.pull("openai", "2026-03-01", "2026-03-02", http=_openai_http)
    ai2 = pd.read_csv(inputs.path_for(ws / "raw", "ai_usage.csv"), encoding="utf-8-sig")
    assert len(ai2) == 3 and (ai2.provider == "Anthropic").sum() == 1


def test_anthropic_range_starts_at_the_api_floor(ws):
    client, calls = _anthropic_client()
    r = providers.anthropic({}, "2025-09-01", "2026-02-01", client=client, today=pd.Timestamp("2026-09-01").date())
    assert calls[0]["starting_at"].startswith("2026-01-01") and r["report"]["warnings"]


# ---------------------------------------------------------------- Microsoft 365
def test_m365_licences_need_a_price(ws, monkeypatch):
    for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.setenv(k, "x")

    def http(method, url, headers=None, body=None, timeout=120):
        if "login" in url:
            return 200, {}, json.dumps({"access_token": "t"}).encode()
        return 200, {}, json.dumps({"value": [
            {"skuPartNumber": "SPE_E3", "prepaidUnits": {"enabled": 50}, "consumedUnits": 41},
            {"skuPartNumber": "VISIO", "prepaidUnits": {"enabled": 5}, "consumedUnits": 2},
            {"skuPartNumber": "FREE", "prepaidUnits": {"enabled": 0}, "consumedUnits": 0}]}).encode()

    connectors.set_config("m365", {"prices": "SPE_E3=36"})
    r = connectors.pull("m365", "2026-08-01", "2026-09-01", http=http, today=pd.Timestamp("2026-09-01").date())
    assert r["ok"] and "VISIO" in r["report"]["warnings"][0]
    sa = _valid(inputs.path_for(ws / "raw", "saas_contracts.csv"), "saas_contracts.csv")
    assert sa.contract.tolist() == ["SPE_E3"] and sa.amount[0] == 1800 and sa.licences_active_30d[0] == 41


# ---------------------------------------------------------------- safety
def test_secrets_never_leave_and_errors_are_explained(ws, monkeypatch):
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "sk-admin-zq9private")
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    s = json.dumps(connectors.status())
    assert "zq9private" not in s
    oa = next(c for c in connectors.status()["connectors"] if c["id"] == "openai")
    assert oa["state"] == "ready" and oa["env"] == [{"name": "OPENAI_ADMIN_KEY", "set": True}]
    r = connectors.pull("openai", "2026-03-01", "2026-03-02",
                        http=lambda *a, **k: (401, {}, b'{"error": "invalid key"}'))
    assert not r["ok"] and "401" in r["error"] and "zq9private" not in json.dumps(r)
    assert not connectors.pull("m365", "2026-03-01", "2026-03-02")["ok"]          # missing variables: a message, no crash
    with pytest.raises(ValueError):
        connectors.pull("openai", "2026-03-02", "2026-03-01")
    connectors.set_config("azure_cost", {"scope": "subscriptions/1", "client_secret": "nope"})   # unknown keys are dropped
    assert "client_secret" not in (ws / "connectors.json").read_text(encoding="utf-8")


def test_env_file_fills_only_missing_variables(tmp_path, monkeypatch):
    from greenledger.config import load_env_file
    p = tmp_path / ".env"
    p.write_text("# comment\nKW_A=from_file\nexport KW_B='quoted'\nKW_C=\n", encoding="utf-8")
    monkeypatch.setenv("KW_A", "from_shell")
    monkeypatch.delenv("KW_B", raising=False)
    names = load_env_file(p)
    import os
    assert os.environ["KW_A"] == "from_shell" and os.environ["KW_B"] == "quoted" and names == ["KW_B"]
    monkeypatch.delenv("KW_B")


def test_azure_token_only_goes_to_azure(ws, monkeypatch):
    """The polling URL comes from Azure's answer; a foreign host there must not receive the access token."""
    for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.setenv(k, "x")
    sent = []

    def http(method, url, headers=None, body=None, timeout=120):
        sent.append((url, (headers or {}).get("Authorization")))
        if "login.microsoftonline.com" in url:
            return 200, {}, json.dumps({"access_token": "tok"}).encode()
        if "generateCostDetailsReport" in url:
            return 202, {"Location": "https://evil.example.com/steal"}, b""
        raise AssertionError(url)

    connectors.set_config("azure_cost", {"scope": "subscriptions/1"})
    r = connectors.pull("azure_cost", "2026-03-01", "2026-03-02", http=http, poll_s=0)
    assert not r["ok"] and "no Azure status URL" in r["error"]
    assert not any("evil" in u for u, _ in sent)
