# External open data for the chat assistant

Used only by the optional AI part (docs/chatbot_rag_finetune.md). The core pipeline never reads these files, so the
case numbers do not depend on them. The datasets and the large reference originals (PDFs, Ember CSVs) are
git-ignored: download them again with the commands below. The passages extracted from the reference documents are
committed in `data/processed/reference_cache.json`, so `greenledger build` produces the same knowledge base without
the originals. Each dataset keeps its own licence; cite them when you reuse the model or the data.

## reference/: indexed for retrieval as "reference document, not company data"

| File | What it is | Licence / source |
|---|---|---|
| `ghg_protocol_scope2_guidance.pdf` | GHG Protocol Scope 2 Guidance (WRI/WBCSD 2015): location-based vs market-based | free download, ghgprotocol.org/sites/default/files/GHG%20Protocol%20Scope%202%20Guidance.pdf |
| `ccf_methodology.md` | Cloud Carbon Footprint methodology: the energy model the pipeline uses | Apache 2.0, github.com/cloud-carbon-footprint/cloud-carbon-footprint (microsite/docs/Methodology.md) |
| `focus_spec_v1_4.pdf` | FinOps FOCUS specification v1.4: standard cost and usage columns | CC BY 4.0, focus.finops.org |
| `ember_yearly_countries.csv`, `ember_yearly_global.csv` | Ember yearly electricity data: grid CO2 intensity per country (used as a cross-check of factors.py for CH, DE, IE, EU) | CC BY 4.0, ember-energy.org/data/yearly-electricity-data |

## grid/: European grid data for the Grid page (core build reads it if present)

| File | What it is | Licence / source |
|---|---|---|
| `release_generation_monthly_lower.csv` | Ember monthly electricity data, Europe: generation by source, emissions, demand, net imports | CC BY 4.0, ember-energy.org/data/monthly-electricity-data |
| `release_generation_yearly_lower.csv` | Ember yearly electricity data, Europe | CC BY 4.0, ember-energy.org/data/yearly-electricity-data |
| `european_wholesale_electricity_price_data_monthly.csv` | Ember day-ahead wholesale prices per country and month | CC BY 4.0, ember-energy.org/data/european-wholesale-electricity-price-data |

| `cross_border_flows_monthly.csv`, `cross_border_net_import_by_hour.csv` | aggregates of 12 months of 15-minute cross-border physical flows per country (Energy-Charts API /v2/cbpf, data from ENTSO-E) | CC BY 4.0, attribution energy-charts.info |
| `ne_50m_admin_0_countries.geojson` | country shapes; projected and simplified into `src/greenledger/assets/europe_map.json` (committed) | public domain, naturalearthdata.com |

Download or refresh: `uv run greenledger grid-fetch` (Ember updates twice a month). Without these files the Grid page explains how to get them; nothing else changes.

## finetune/: behaviour examples for the LoRA fine-tuning (a small, filtered sample of each)

| Folder | Teaches | Licence / source |
|---|---|---|
| `squad_v2/` | answer from a passage, or say "not in the data" when the passage has no answer | CC BY-SA 4.0, huggingface.co/datasets/rajpurkar/squad_v2 |
| `tat_qa/` | read figures exactly from tables (span answers only; arithmetic answers are excluded: the assistant never computes figures) | CC BY 4.0, github.com/NExTplusplus/TAT-QA (paper: non-commercial use) |
| `rag_12k/` | grounded answers from a given context (only examples whose figures are all in the context) | Apache 2.0 + Falcon RefinedWeb terms, huggingface.co/datasets/neural-bridge/rag-dataset-12000 |
| `prompt_injections/` | refuse injected instructions (label 1); off-topic questions -> not in the data (label 0) | Apache 2.0, huggingface.co/datasets/deepset/prompt-injections |

## Download again (from the project root)

```bash
H="uv run --no-project --with huggingface_hub hf download"
$H rajpurkar/squad_v2 --repo-type dataset --local-dir data/raw/external/finetune/squad_v2
$H neural-bridge/rag-dataset-12000 --repo-type dataset --local-dir data/raw/external/finetune/rag_12k
$H deepset/prompt-injections --repo-type dataset --local-dir data/raw/external/finetune/prompt_injections
for s in train dev test_gold; do curl -sSfL -o data/raw/external/finetune/tat_qa/tatqa_dataset_$s.json \
  https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/dataset_raw/tatqa_dataset_$s.json; done
```

The deepset files are expected as `prompt_injections/train.parquet` and `test.parquet` (rename them after a fresh
download, or keep the `data/` sub-folder: the loader searches the folder recursively).
