"""Sources page: every input file, every conversion factor and every published figure Kilowise uses, linked to a
numbered reference list.

The reference list below is curated (publisher, year, title, link, licence, accessed). What each reference is USED FOR
is not typed by hand: build() matches each reference's `match` strings against the source texts the code already
carries (factors.py, grid.py, ai_models.py), so a new factor or figure shows up here with its reference, and one
without a matching reference is listed as unreferenced (a test keeps that list to stated assumptions only).
"""
from __future__ import annotations

from . import ai_models, grid, gridflows
from . import factors as F

KINDS = {
    "company": "Company data",
    "open": "Open data downloaded",
    "statistics": "Official statistics and published figures",
    "factor": "Conversion factors",
    "models": "AI models: prices, sizes, training",
    "method": "Methods and standards",
    "software": "Software, models and datasets used to build Kilowise",
}


# Plain names for the factor keys of factors.py (the key stays the id; unknown keys get a readable fallback).
LABELS = {
    "grid_ch_consumption": "Grid CO₂, Switzerland (consumption mix)", "grid_ch_production": "Grid CO₂, Switzerland (production mix)",
    "grid_de": "Grid CO₂, Germany", "grid_ie": "Grid CO₂, Ireland", "grid_eu_mixed": "Grid CO₂, EU average (AI services and SaaS)",
    "grid_market_ch": "Market-based CO₂, Switzerland", "grid_market_residual_eu": "Market-based CO₂, European residual mix",
    "server_overhead_multiplier": "Server overhead multiplier", "gpu_idle_w": "GPU idle power",
    "storage_kwh_per_gb_day": "Storage energy per GB and day", "network_kwh_per_gb": "Network energy per GB",
    "kwh_per_1000_tokens": "AI energy per 1,000 tokens", "small_model_energy_share": "Small model energy, share of a large one",
    "kwh_per_message": "Energy per chat message", "saas_kwh_per_active_user_month": "SaaS energy per active user and month",
    "pue_azure": "PUE, Azure", "pue_aws": "PUE, AWS", "pue_hoster": "PUE, Swiss hoster",
    "wh_per_1000_output_tokens_per_billion_active_params": "Energy per output token and model size",
    "input_token_energy_weight": "Energy of an input token, share of an output token", "grid_us_average": "Grid CO₂, United States",
    "grid_china_average": "Grid CO₂, China", "training_gpu_kw": "GPU power during training", "training_pue": "PUE of training clusters",
}
label = lambda key: LABELS.get(key) or key.replace("_", " ").capitalize()


def _ref(id, kind, publisher, year, title, url, licence="", match=(), accessed="", note="", uses=()):
    return {"id": id, "kind": kind, "publisher": publisher, "year": year, "title": title, "url": url, "licence": licence,
            "match": list(match), "accessed": accessed, "note": note, "uses": list(uses)}


REFERENCES = [
    # ---- company data ----
    _ref("altyca", "company", "ALTYCA", 2026, "Green AI & Data case: sample exports of a Swiss SME (synthetic data) and the two "
         "submission templates", "", "Case material of sprintd Basel 2026", match=["Sample data ALTYCA"],
         note="Cite as 'Sample data ALTYCA, sprintd Basel 2026'. Every ledger figure starts here."),
    # ---- open data ----
    _ref("ember-m", "open", "Ember", 2026, "Monthly electricity data, Europe (generation by source, emissions, demand, net imports)",
         "https://ember-energy.org/data/monthly-electricity-data/", "CC BY 4.0", ["monthly electricity data", "release_generation_monthly"], "2026-11-21"),
    _ref("ember-y", "open", "Ember", 2026, "Yearly electricity data, Europe", "https://ember-energy.org/data/yearly-electricity-data/",
         "CC BY 4.0", ["yearly electricity data", "release_generation_yearly", "Ember / IEA"], "2026-11-21"),
    _ref("ember-p", "open", "Ember", 2026, "European wholesale electricity price data (day-ahead, monthly)",
         "https://ember-energy.org/data/european-wholesale-electricity-price-data/", "CC BY 4.0",
         ["wholesale electricity prices", "european_wholesale"], "2026-11-21", "Prices from ENTSO-E, EMR and SEMOpx, compiled by Ember."),
    _ref("ember-meth", "method", "Ember", 2026, "Electricity data methodology (life-cycle emission factors per fuel)",
         "https://files.ember-energy.org/public-downloads/ember_electricity_data_methodology.pdf", "CC BY 4.0",
         ["life-cycle factors per fuel"], "2026-11-21"),
    _ref("echarts", "open", "Fraunhofer ISE, Energy-Charts", 2026, "Cross-border physical flows, every 15 minutes (API /v2/cbpf; data from ENTSO-E)",
         "https://api.energy-charts.info/", "CC BY 4.0, attribution energy-charts.info", ["energy-charts", "15-minute cross-border"], "2026-11-21"),
    _ref("natearth", "open", "Natural Earth", 2024, "Admin 0 countries, 1:50m", "https://www.naturalearthdata.com/", "Public domain",
         ["Natural Earth"], "2026-11-21", "Projected with the Lambert azimuthal equal-area projection (EPSG:3035 centre) and simplified."),
    # ---- grid factors ----
    _ref("bfe-2026", "factor", "BFE / treeze", 2026, "Energieetikette Personenwagen: Umweltkennwerte 2026 (Swiss consumer mix 2022-2024; supplier mix 2024)",
         "https://pubdb.bfe.admin.ch/de/publication/download/12674", "Swiss federal publication", ["12674"], "2026-11-20"),
    _ref("bfe-2023", "factor", "BFE / treeze", None, "Umweltkennwerte, Swiss consumer mix 2021-2023",
         "https://pubdb.bfe.admin.ch/de/publication/download/12224", "Swiss federal publication", ["12224"], "2026-11-20"),
    _ref("vse", "factor", "VSE (Swiss electricity industry association)", 2025, "CO2-Gehalt Strommix Schweiz",
         "https://www.strom.ch/de/media/15408/download", "", ["strom.ch"], "2026-11-20"),
    _ref("bafu-mix", "factor", "treeze for BAFU", None, "Umweltbilanz Strommix Schweiz 2018, v2.01", "https://www.bafu.admin.ch/",
         "Swiss federal publication", ["Umweltbilanz Strommix"], "2026-11-20"),
    _ref("uba", "factor", "Umweltbundesamt", 2025, "CO2-Emissionen pro Kilowattstunde Strom 2024",
         "https://www.umweltbundesamt.de/themen/co2-emissionen-pro-kilowattstunde-strom-2024", "", ["Umweltbundesamt"], "2026-11-20"),
    _ref("epa-ie", "factor", "EPA Ireland", 2025, "Ireland's provisional greenhouse gas emissions 1990-2024", "https://www.epa.ie/publications/",
         "", ["EPA Ireland"], "2026-11-20"),
    _ref("eea", "factor", "European Environment Agency", 2025, "Greenhouse gas emission intensity of electricity generation (indicator)",
         "https://www.eea.europa.eu/en/analysis/indicators/greenhouse-gas-emission-intensity-of-1", "CC BY 4.0", ["eea.europa.eu"], "2026-11-20"),
    _ref("aib", "factor", "Association of Issuing Bodies (AIB)", 2025, "European Residual Mixes 2024",
         "https://www.aib-net.org/facts/european-residual-mix/2024", "", ["aib-net.org"], "2026-11-21"),
    _ref("egrid", "factor", "US EPA", 2024, "eGRID 2022 summary tables", "https://www.epa.gov/egrid", "Public domain (US government)", ["eGRID"], "2026-11-21"),
    _ref("emaps", "factor", "Electricity Maps", 2026, "Grid in review 2025: Switzerland", "https://www.electricitymaps.com/grid-in-review-2025/switzerland",
         "", ["electricitymaps.com"], "2026-11-21"),
    _ref("unige", "factor", "University of Geneva, Energy Systems", None, "Hourly CO2 content of the Swiss electricity mix (CO2 calculator)",
         "https://www.unige.ch/sysener/services/CO2", "", ["unige.ch"], "2026-11-21"),
    # ---- data centre energy ----
    _ref("ccf", "method", "Thoughtworks, Cloud Carbon Footprint", 2024, "Methodology: energy and emissions of cloud usage",
         "https://www.cloudcarbonfootprint.org/docs/methodology", "Apache 2.0", ["cloudcarbonfootprint", "Cloud Carbon Footprint"], "2026-11-20"),
    _ref("aws-fs", "factor", "Amazon Web Services", 2026, "AWS sustainability fact sheets: Switzerland, Ireland (PUE 2023-2025)",
         "https://sustainability.aboutamazon.com/aws-sustainability-fact-sheets/aws-fact-sheet-switzerland.pdf", "",
         ["aws-sustainability-fact-sheets", "AWS sustainability fact sheets"], "2026-11-21"),
    _ref("azure-pue", "factor", "Microsoft", None, "Azure datacenter design PUE (blog)", "https://azure.microsoft.com/en-us/blog/", "",
         ["azure.microsoft.com blog"], "2026-11-20"),
    _ref("uptime", "factor", "Uptime Institute", 2024, "Global Data Center Survey 2024 (average PUE)", "https://intelligence.uptimeinstitute.com/",
         "", ["Uptime Institute"], "2026-11-20"),
    # ---- AI energy ----
    _ref("google-ai", "factor", "Google Cloud", 2025, "Measuring the environmental impact of AI inference",
         "https://cloud.google.com/blog/products/infrastructure/measuring-the-environmental-impact-of-ai-inference", "",
         ["measuring-the-environmental-impact-of-ai-inference", "Google Gemini, median text prompt", "Google 2025"], "2026-11-20"),
    _ref("openai-cbs", "factor", "CBS News", 2025, "OpenAI CEO: 0.34 Wh per ChatGPT query (2025-08-21)", "https://www.cbsnews.com/", "",
         ["CBS News", "OpenAI (0.34"], "2026-11-20"),
    _ref("mlenergy", "factor", "Chung et al., ML.ENERGY", 2025, "The ML.ENERGY Benchmark and Leaderboard (arXiv 2505.06371)",
         "https://ml.energy/leaderboard", "", ["ml.energy", "ML.ENERGY"], "2026-11-21"),
    _ref("leadgreen", "factor", "LeadGreen", 2025, "AI energy index (compiles ML.ENERGY measurements)", "https://leadgreen.ai/index", "",
         ["leadgreen.ai"], "2026-11-21"),
    # ---- statistics: data centres, cloud regions ----
    _ref("cso-ie", "statistics", "Central Statistics Office Ireland", 2026, "Data Centres Metered Electricity Consumption 2024 and 2025",
         "https://www.cso.ie/en/releasesandpublications/ep/p-dcmec/", "Reuse with attribution (CSO)", ["CSO Ireland"], "2026-11-21"),
    _ref("cbs-nl", "statistics", "CBS Statistics Netherlands", 2026, "Data centres consume 5 percent of the Netherlands' electricity",
         "https://www.cbs.nl/en-gb/news/2026/47/data-centres-consume-5-percent-of-the-netherlands-electricity", "CC BY 4.0", ["CBS Netherlands"], "2026-11-21"),
    _ref("bitkom", "statistics", "Bitkom / Borderstep Institute", 2025, "Rechenzentren in Deutschland, Studienbericht 2025",
         "https://www.bitkom.org/sites/main/files/2025-11/bitkom-studienbericht-rechenzentren-2025.pdf", "", ["Bitkom"], "2026-11-21"),
    _ref("bfe-dc", "statistics", "BFE / EnergieSchweiz", 2026, "Electricity consumption and efficiency of data centres in Switzerland",
         "https://pubdb.bfe.admin.ch/", "Swiss federal publication", ["data centre study"], "2026-11-21"),
    _ref("iea-owid", "statistics", "IEA, processed by Our World in Data", 2026, "Energy and AI: share of electricity demand used by data centres",
         "https://ourworldindata.org/grapher/data-centers-share-electricity-demand", "CC BY 4.0 (OWID); IEA terms for the source data",
         ["Energy and AI"], "2026-11-21"),
    _ref("regions", "statistics", "Microsoft, Amazon, Google", 2026, "Cloud region pages (Azure geographies, AWS regions, Google Cloud locations)",
         "https://azure.microsoft.com/explore/global-infrastructure/geographies", "", ["Provider region pages"], "2026-11-21"),
    # ---- AI models ----
    _ref("p-anthropic", "models", "Anthropic", 2026, "API pricing", "https://platform.claude.com/docs/en/about-claude/pricing", "", ["platform.claude.com"], "2026-11-21"),
    _ref("p-openai", "models", "OpenAI", 2026, "API pricing", "https://developers.openai.com/api/docs/pricing", "", ["developers.openai.com"], "2026-11-21"),
    _ref("p-google", "models", "Google", 2026, "Gemini API pricing", "https://aistudio.google.com/", "", ["aistudio.google.com"], "2026-11-21"),
    _ref("p-mistral", "models", "Mistral AI", 2026, "API pricing", "https://mistral.ai/pricing", "", ["mistral.ai/pricing"], "2026-11-21"),
    _ref("p-together", "models", "Together AI", 2026, "Serverless model prices", "https://docs.together.ai/", "", ["docs.together.ai", "Together AI"], "2026-11-21"),
    _ref("p-publicai", "models", "Artificial Analysis", 2026, "Apertus 70B providers and prices", "https://artificialanalysis.ai/models/apertus-70b-instruct/providers",
         "", ["artificialanalysis.ai"], "2026-11-21"),
    _ref("medec", "models", "Ben Abacha et al.", 2024, "MEDEC: a benchmark for medical error detection (size estimates of closed models; arXiv 2412.19260)",
         "https://arxiv.org/abs/2412.19260", "", ["MEDEC"], "2026-11-21"),
    _ref("llama", "models", "Meta", 2024, "Llama 3.1 and Llama 4 model cards (GPU hours, location-based tCO2e)", "https://github.com/meta-llama",
         "", ["Llama 3.1 model card", "Llama 4 model card", "Llama model cards"], "2026-11-21"),
    _ref("mistral-lca", "models", "Mistral AI with Carbone 4 and ADEME", 2025, "Our contribution to a global environmental standard for AI",
         "https://mistral.ai/news/", "", ["global environmental standard for AI"], "2026-11-21"),
    _ref("gptoss", "models", "OpenAI", 2025, "gpt-oss-120b and gpt-oss-20b model card (arXiv 2508.10925)", "https://arxiv.org/abs/2508.10925", "",
         ["gpt-oss model card"], "2026-11-21"),
    _ref("dsv3", "models", "DeepSeek-AI", 2024, "DeepSeek-V3 technical report (arXiv 2412.19437)", "https://arxiv.org/abs/2412.19437", "",
         ["DeepSeek-V3 technical report"], "2026-11-21"),
    _ref("dsv3-price", "models", "S. Willison", 2024, "Notes on DeepSeek V3 launch pricing", "https://simonwillison.net/2024/Dec/26/deepseek-v3/", "",
         ["simonwillison.net"], "2026-11-21"),
    _ref("apertus", "models", "Swiss AI Initiative (EPFL, ETH Zurich, CSCS)", 2025, "Apertus: democratizing open and compliant LLMs (arXiv 2509.14233)",
         "https://arxiv.org/abs/2509.14233", "", ["Apertus report", "arXiv 2509.14233"], "2026-11-21"),
    _ref("mistral3", "models", "Mistral AI", 2025, "Introducing Mistral 3", "https://mistral.ai/news/", "", ["Mistral 3 announcement"], "2026-11-21"),
    _ref("patterson", "models", "Patterson et al.", 2021, "Carbon emissions and large neural network training (arXiv 2104.10350)",
         "https://arxiv.org/abs/2104.10350", "", ["Patterson et al."], "2026-11-21"),
    _ref("bloom", "models", "Luccioni, Viguier, Ligozat", 2023, "Estimating the carbon footprint of BLOOM, a 176B parameter language model (JMLR 24)",
         "https://jmlr.org/papers/v24/23-0069.html", "CC BY 4.0", ["Estimating the Carbon Footprint of BLOOM"], "2026-11-21"),
    _ref("aiindex", "models", "Stanford HAI", 2025, "AI Index Report 2024 and 2025 (training cost estimates, Epoch AI data)", "https://hai.stanford.edu/ai-index",
         "", ["Stanford AI Index"], "2026-11-21"),
    _ref("press-ai", "models", "Press reports", 2025, "AP, The Register, SemiAnalysis, Semafor, Amazon, OpenAI, DatacenterDynamics, Medium: "
         "training sites, water use and costs of GPT-4, DeepSeek V3, Claude (Project Rainier), Gemini, Mistral", "", "",
         ["thestreet.com", "theregister.com", "semianalysis.com", "Project Rainier", "semafor.com", "openai.com/index/building",
          "datacenterdynamics.com", "medium.com/data-science", "arXiv 2601.06174", "Gemini technical report"], "2026-11-21",
         "Outside estimates; each value on the Models page says whether it is published, an estimate or calculated."),
    # ---- methods and standards ----
    _ref("ghgp", "method", "WRI / WBCSD", 2015, "GHG Protocol Scope 2 Guidance (location-based and market-based methods)",
         "https://ghgprotocol.org/scope-2-guidance", "Free download", ["Scope 2"], "2026-11-20"),
    _ref("focus", "method", "FinOps Foundation", 2025, "FOCUS specification v1.4 (standard cost and usage columns)", "https://focus.finops.org/",
         "CC BY 4.0", ["FOCUS"], "2026-11-20"),
    _ref("epsg3035", "method", "EPSG", None, "EPSG:3035, ETRS89 / LAEA Europe (map projection)", "https://epsg.io/3035", "", ["EPSG:3035"], ""),
    _ref("entsoe", "method", "ENTSO-E", 2026, "Transparency Platform: the source of the cross-border flows and day-ahead prices used here",
         "https://transparency.entsoe.eu/", "ENTSO-E terms", ["ENTSO-E"], ""),
    # ---- software, models and datasets used to build Kilowise ----
    _ref("claude-code", "software", "Anthropic", 2026, "Claude Code: AI coding assistant used to write code, tests and documentation",
         "https://claude.com/claude-code", "", [], "", "Its energy use is reported in the sidebar (our own AI use).",
         ["code, tests and documentation of Kilowise", "own AI use in the sidebar"]),
    _ref("qwen", "software", "Alibaba Qwen team", 2024, "Qwen2.5-1.5B-Instruct: base model of the assistant, fine-tuned with LoRA",
         "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct", "Apache 2.0", ["Qwen2.5-1.5B"], ""),
    _ref("minilm", "software", "sentence-transformers", 2021, "all-MiniLM-L6-v2: sentence embeddings for retrieval",
         "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2", "Apache 2.0", [], "", "", ["assistant: retrieval"]),
    _ref("ds-ft", "software", "Rajpurkar et al.; Zhu et al.; neural-bridge; deepset", 2018, "SQuAD 2.0, TAT-QA, RAG-12k and prompt-injections: "
         "training and evaluation data of the assistant", "https://huggingface.co/datasets", "CC BY-SA 4.0; CC BY 4.0; Apache 2.0; Apache 2.0", [], "",
         "Small filtered samples; licences per dataset in data/raw/external/README.md.", ["assistant: fine-tuning and evaluation"]),
    _ref("simpleicons", "software", "Simple Icons contributors", 2026, "Simple Icons 16.38: brand marks of Anthropic, Google Cloud, "
         "Zoom and Atlassian on the Data sources page", "https://simpleicons.org/", "CC0 1.0 for the SVG data; trademarks belong to "
         "their owners", [], "2026-11-21", "Brands that asked to be removed from open icon sets (AWS, Microsoft, OpenAI, Slack, "
         "Salesforce) are shown as a wordmark in their brand colour instead.", ["provider tiles on Data sources"]),
    _ref("libs", "software", "Open-source projects", 2026, "pandas, NumPy, scikit-learn, pytest; PyTorch, transformers, PEFT for the assistant",
         "https://pypi.org/", "BSD-3 / MIT / Apache 2.0", [], "", "", ["pipeline, tests, ML models, assistant"]),
]


def _texts(data: dict) -> list[tuple[str, str, str]]:
    """(where, label, source text) for every figure that names its source."""
    out = [("factor", label(f.key), f.source + " " + f.note) for f in F.ALL_FACTORS]
    out += [("factor", "Server power per vCPU", F.CCF_SOURCE), ("factor", "Hourly Swiss CO₂ profile", F.HOURLY_SOURCE)]
    out += [("statistics", f"data centres {d['iso3']} {d['year']}", d["source"]) for d in grid.DATA_CENTRES]
    out += [("statistics", f"data centres {d['iso3']} {d['year']} outlook", d["source"]) for d in grid.DATA_CENTRE_OUTLOOK]
    out += [("statistics", "data centres Europe", grid.EUROPE_DC_SHARE["source"]), ("statistics", "cloud regions", grid.CLOUD_SOURCE)]
    out += [("open", t, src) for t, src in ((grid.FILES[k][2], grid.FILES[k][2]) for k in grid.FILES)]
    out += [("open", "cross-border flows", gridflows.FLOW_SOURCE), ("open", "map of Europe", gridflows.MAP_SOURCE),
            ("method", "map projection", "EPSG:3035 Lambert azimuthal equal-area")]
    g = data.get("grid") or {}
    if g.get("method"):
        out += [("method", "Grid: " + k, v) for k, v in g["method"].items()]
    out += [("models", f"Models: {k}", v) for k, v in ai_models.SRC.items()]
    md = data.get("ai_models") or {}
    for r in md.get("training_runs", []):
        out.append(("models", f"training run {r['model']}", " ".join(r["sources"])))
    out += [("company", "ledger", "Sample data ALTYCA"), ("method", "CO₂ views", "GHG Protocol Scope 2 location-based market-based"),
            ("method", "FOCUS", "FinOps FOCUS columns (Data sources page, future provider mapping)"),
            ("software", "assistant", "Qwen2.5-1.5B")]
    return out


def build(data: dict) -> dict:
    texts = _texts(data)
    refs = [dict(r) for r in REFERENCES]
    for r in refs:
        r["used_for"] = sorted({label for _, label, txt in texts if any(m.lower() in txt.lower() for m in r["match"])} | set(r["uses"]))
    order = list(KINDS)
    refs.sort(key=lambda r: (order.index(r["kind"]), r["publisher"].lower(), -(r["year"] or 0)))
    for i, r in enumerate(refs, 1):
        r["n"] = i
    # factors: which numbered references back each one; flagged when none does (stated assumptions)
    factors = []
    for f in F.ALL_FACTORS:
        txt = (f.source + " " + f.note).lower()
        ns = [r["n"] for r in refs if any(m.lower() in txt for m in r["match"])]
        factors.append({"key": f.key, "label": label(f.key), "low": f.low, "mid": f.mid, "high": f.high, "unit": f.unit, "source": f.source,
                        "note": f.note, "refs": ns, "assumption": f.source.lower().startswith("assumption") or "assumption" in f.source.lower()})
    unreferenced = [f["key"] for f in factors if not f["refs"]]
    assert len({f["label"] for f in factors}) == len(factors), "two factors with the same label"
    return {"kinds": KINDS, "references": refs, "factors": factors, "unreferenced": unreferenced,
            "cite": "Sample data ALTYCA, sprintd Basel 2026. Grid data: Ember (CC BY 4.0); cross-border flows: Energy-Charts / "
                    "Fraunhofer ISE (CC BY 4.0); map: Natural Earth (public domain)."}
