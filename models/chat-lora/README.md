# GreenLedger chat adapter (LoRA)

LoRA adapter for **Qwen/Qwen2.5-1.5B-Instruct** (Apache 2.0) that answers questions about the GreenLedger ledger **only from
retrieved facts**, cites them as [n], says "That is not in the data." when the facts do not hold the answer, and
refuses injected instructions. Built by `uv run --group finetune greenledger finetune` (src/greenledger/finetune.py);
served by `greenledger serve` / `greenledger chat` (src/greenledger/chat.py). Status: **kept**.
Fine-tuned score 0.815 > base + RAG 0.276: adapter kept.

## Evaluation (181 held-out test questions, same retrieved facts for both)

| Metric | Base + RAG | Fine-tuned + RAG |
|---|---|---|
| Exact-number accuracy | 39.8% | 71.6% |
| Citation rate (gold fact cited) | 3.1% | 96.1% |
| Ledger questions fully correct | 13.0% | 77.8% |
| Says "not in the data" when it is not there | 67.6% | 70.3% |
| Refuses injected orders (model alone, no guard) | 0.0% | 88.2% |
| Score (mean of number, citation, abstention, refusal) | 27.6% | 81.5% |

## Training

LoRA (bf16, all attention + MLP projections); r = 16, 2.0 epochs, 184 steps,
lr 0.0002, effective batch 16, 1486 examples (99 longer than
1280 tokens dropped), loss on answer tokens only, seed 42, NVIDIA GeForce RTX 4060 Laptop GPU.

Data (split 80/10/10 by fact): {"train": {"rows": 1585, "ledger": 570, "squad": 269, "tatqa": 252, "rag12k": 246, "deepset": 248}, "val": {"rows": 185, "ledger": 54, "squad": 30, "tatqa": 32, "rag12k": 37, "deepset": 32}, "test": {"rows": 181, "ledger": 54, "squad": 21, "tatqa": 36, "rag12k": 37, "deepset": 33}}
- ledger: questions about the sample SME's ledger with answers written by code (correct by construction)
- SQuAD 2.0 (CC BY-SA 4.0), TAT-QA span answers (CC BY 4.0), neural-bridge RAG-12k (Apache 2.0 + Falcon RefinedWeb
  terms), deepset prompt-injections (Apache 2.0). Sources and licences: data/raw/external/README.md.

## Energy

Measured GPU board power (nvidia-smi) for training and evaluation: 0.88 GPU-hours, 0.037 kWh x Swiss consumption mix 0.094 kg/kWh (laptop in Switzerland). CPU, RAM and display are not included (add about 30-50 %).

## Limits

- Trained on synthetic sample data (ALTYCA, sprintd Basel 2026). Retrain with `greenledger finetune` for new data.
- The model can still mis-explain a reason that is not in the facts; figures are protected by the number check in
  chat.py (any figure not in the retrieved facts is replaced), reasoning is not. Answers always list their sources.
- Off-topic chit-chat is sometimes refused instead of answered with "not in the data" (both decline).
