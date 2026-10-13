# Prompt Injection Firewall: Multi-Layer Defense for International & Vietnamese LLMs

A production-grade, multi-layer AI Security and LLM Safety system designed to detect and neutralize **prompt injection, jailbreak attempts, privilege escalation, and unsafe agent actions** across both **international benchmarks** and **Vietnamese conversational environments**.

---

## Architecture Overview

```text
User / Agent Prompt
        │
        ▼
[ Layer 1: Fast Prefilter (< 10ms) ]
  ├── Regex Engine (EN & VI: roleplay, admin override, prompt leak, teencode)
  └── ChromaDB Vector Similarity (149 curated EN & VI jailbreak patterns)
        │ ── BLOCK (Known Attack / Vector >= 0.85)
        │ ── PASS (Clean / No Cues)
        └── ESCALATE (Borderline / Similarity in [0.60, 0.85))
        ▼
[ Layer 2: XGBoost Feature Classifier (< 25ms) ]
  ├── 32 Syntactic, Structural, & Semantic Features
  └── Vietnamese Features: token counts, role claims, teencode, urgency, privilege phrases
        │ ── BLOCK (Confidence >= 0.85)
        │ ── ALLOW (Confidence < 0.50)
        └── ESCALATE (Confidence in [0.50, 0.85) or subtle exploit patterns)
        ▼
[ Layer 3: Deep Sequence Classifier (< 80ms) ]
  ├── Multilingual Transformer / DistilBERT (`distilbert-base-multilingual-cased`, XLM-R)
  └── Two-Stage Curriculum Fine-Tuning: Stage A (International) -> Stage B (Vietnamese)
        │ ── BLOCK (Malicious prob >= 0.60)
        └── ALLOW (Malicious prob < 0.60)
        ▼
[ Layer 4: Enterprise Policy Validator ]
  └── Strict Pydantic v2 Business Logic Rules:
      ├── Refund Validation (Role authorization & amount capping)
      ├── Money Transfer Policy (Mandatory 2FA OTP, transaction limits by role)
      ├── Account Recovery & Password Reset (Anti-override, mandatory audit ticket)
      ├── Voucher & Discount Abuse (Max discount capping, role privilege)
      └── Privilege Escalation & Access Control (Anti self-escalation)
```

---

## Dataset Pipeline: International + Vietnamese

The firewall trains on a unified, balanced dataset combining leading international benchmarks and specialized Vietnamese datasets:

| Dataset Source | Description | Language | Focus |
| :--- | :--- | :--- | :--- |
| `deepset/prompt-injections` | International benchmark | English | Direct & indirect prompt injections |
| `tmdeptrai3012/prompt-injection-dataset-vi-en` | Public bilingual dataset | Vietnamese / English / Mixed | Goal hijacking, prompt leaking, roleplay bypass |
| `dangvansam/vietnamese-prompt-injection` | Vietnamese injection dataset | Vietnamese | Direct injections & jailbreaks |
| `data/raw/vietnamese_seed_samples.jsonl` | Curated seed repository | Vietnamese | Admin override, urgency, teencode, financial abuse |
| `MAlmasabi/Indirect-Prompt-Injection-BIPIA-GPT` | Optional indirect benchmark | English | RAG / document-based indirect injections |

### Unified Record Schema
Every sample is cleaned, normalized, and saved to `data/processed/ground_truth_mixed.csv` with:
- `text`: Original input text
- `normalized_text`: Cleaned text with Unicode NFC and teencode expansion
- `label`: `"SAFE"` or `"INJECTION_PROMPT"`
- `label_binary`: `0` (safe) or `1` (malicious)
- `dataset_source`: Originating dataset tag
- `language`: `"vi"`, `"en"`, or `"mixed"`
- `attack_type`: `"safe"`, `"direct_injection"`, `"jailbreak_roleplay"`, `"prompt_leaking"`, `"privilege_escalation"`, `"obfuscation"`

### Preprocessing & Normalization Features
Located in `data/scripts/vietnamese_norm.py`:
- **Unicode NFC Normalization**: Standardizes precomposed vs decomposed accents.
- **Vietnamese Accent Stripping**: Converts text to unaccented form to detect bypasses without diacritics.
- **Teencode & Slang Expansion**: Normalizes abbreviations (`ko`/`k` -> `không`, `dc`/`đc` -> `được`, `mk` -> `mật khẩu`, `tk`/`acc` -> `tài khoản`, `ad` -> `quản trị viên`, `pass` -> `mật khẩu`).
- **Conflict Resolution**: Removes ambiguous prompts with conflicting labels across multiple dataset sources.

---

## Quickstart & Installation

### 1. Environment Setup

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Linux / macOS
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Prepare Mixed Datasets

Prepare both international and Vietnamese datasets into unified schemas:

```bash
python data/scripts/prepare_real_datasets.py --include-vietnamese
```

*Output files:*
- `data/processed/ground_truth_mixed.csv` (Full dataset)
- `data/processed/ground_truth.csv`
- `data/processed/ground_truth_layer3_mixed.csv` (Layer 3 subset)
- `data/processed/real_train.csv`, `real_validation.csv`, `real_test.csv`

---

## Model Training & Evaluation

### Layer 1: Vector Prefilter ChromaDB
Rebuild the vector database embedding 149 English and Vietnamese jailbreak patterns:

```bash
python models/layer1_prefilter/build_vector_db.py
```

### Layer 2: XGBoost Feature Classifier
Extract 32 features and train the XGBoost classifier:

```bash
# 1. Extract feature matrix
python models/layer2_xgboost/build_feature_dataset.py

# 2. Train XGBoost and print per-language evaluation
python models/layer2_xgboost/train.py
```

**Evaluation Output:**
```text
================ LAYER 2 MODEL OVERALL EVALUATION ================
Accuracy : 86.90%
Precision: 85.44%
Recall   : 86.54%
F1-Score : 85.99%
ROC-AUC  : 0.9278

================ PER-LANGUAGE EVALUATION METRICS ================
[EN]    (n=227) Acc: 88.55% | Prec: 87.76% | Rec: 86.00% | F1: 86.87% | AUC: 0.9390
[MIXED] (n=19)  Acc: 94.74% | Prec: 93.33% | Rec: 100.0% | F1: 96.55% | AUC: 1.0000
[VI]    (n=90)  Acc: 81.11% | Prec: 77.78% | Rec: 83.33% | F1: 80.46% | AUC: 0.8755
=================================================================
```

### Layer 3: Multilingual Deep Classifier
Train or fine-tune multilingual transformers (`distilbert-base-multilingual-cased`, `xlm-roberta-base`):

```bash
# Standard mixed training
python models/layer3_distilbert/train.py --model-name distilbert-base-multilingual-cased --epochs 3

# Two-stage curriculum fine-tuning (Stage A: International -> Stage B: Vietnamese)
python models/layer3_distilbert/train.py --stage stage_a_intl --epochs 2
python models/layer3_distilbert/train.py --stage stage_b_vi --epochs 3
```

---

## Layer 4 Enterprise Security Policy Schemas

Layer 4 validates function call arguments and agent action requests via Pydantic v2 schemas:

| Action | Allowed Roles | Policy Constraints |
| :--- | :--- | :--- |
| `refund` | `support_agent`, `supervisor`, `finance_lead`, `admin` | Max 110% of order value; `support_agent` capped at $200. |
| `transfer_money` | `user`, `finance_officer`, `treasury_lead`, `admin` | Mandatory 2FA OTP for >= 10M VND / $500; `user` capped at 50M VND; sender != recipient. |
| `account_recovery` / `password_reset` | `user`, `security_admin`, `supervisor` | Mandatory confirmed identity; manual support override restricted to `security_admin` with ticket ID. |
| `voucher_apply` | `customer`, `marketing_manager`, `admin` | Max discount 70% without `marketing_manager`; discount cannot exceed order total. |
| `role_escalation` | `super_admin`, `system_security` | Self-escalation strictly forbidden; `admin`/`root` grants require `super_admin` approval & ticket. |

---

## Running the API & Validation Tests

### Start FastAPI Server
```bash
python -m uvicorn api.main:app --reload
```
Interactive Swagger documentation available at: `http://127.0.0.1:8000/docs`

### Execute Complete Test Suite
Run all 63 unit and integration tests:

```bash
pytest -v
```

---

## Project Structure

```text
.
├── api/
│   ├── main.py                     # FastAPI application endpoints
│   ├── routes/                     # Chat & Action validation routes
│   └── schemas.py                  # API request/response schemas
├── data/
│   ├── chroma_db/                  # Local ChromaDB vector database
│   ├── processed/                  # Normalized datasets (ground_truth_mixed.csv)
│   ├── raw/                        # Seed datasets (vietnamese_seed_samples.jsonl)
│   └── scripts/
│       ├── prepare_real_datasets.py# Master dataset ingestion & split pipeline
│       └── vietnamese_norm.py      # Unicode, accent, teencode, conflict resolver
├── firewall/
│   ├── baseline.py                 # Fast regex baseline with EN & VI patterns
│   ├── layer1.py                   # Prefilter: regex + vector similarity (<10ms)
│   ├── layer2.py                   # XGBoost feature classifier (<25ms)
│   ├── layer3.py                   # Multilingual deep sequence classifier (<80ms)
│   ├── layer4.py                   # Pydantic v2 enterprise security validator
│   └── orchestrator.py             # Dynamic escalation pipeline & execution trace
├── models/
│   ├── layer1_prefilter/
│   │   ├── build_vector_db.py      # ChromaDB vector index builder
│   │   └── jailbreak_patterns.json # 149 curated EN & VI jailbreak patterns
│   ├── layer2_xgboost/
│   │   ├── features.py             # 32 numerical & language features
│   │   ├── build_feature_dataset.py# Feature matrix extractor
│   │   ├── train.py                # Mixed training & per-language metrics
│   │   └── model.pkl               # Persisted XGBoost model
│   └── layer3_distilbert/
│       ├── train.py                # Multilingual transformer training pipeline
│       └── checkpoint/             # Trained deep classifier weights
└── tests/
    ├── test_api.py                 # API endpoints testing
    ├── test_baseline.py            # Baseline regex tests
    ├── test_features.py            # Layer 2 feature tests
    ├── test_layer1.py              # Layer 1 unit tests
    ├── test_layer2.py              # Layer 2 unit tests
    ├── test_layer4.py              # Layer 4 policy tests
    ├── test_orchestrator.py        # End-to-end integration tests
    └── test_vietnamese_firewall.py # 20 Vietnamese & multilingual test cases
```
