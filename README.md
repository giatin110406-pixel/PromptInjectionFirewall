# AI-Powered Threat Detection for Conversational Agents (AI Firewall MVP)

A layered defense system against Prompt Injections, Jailbreaks, and Privilege Escalation attacks in conversational AI agents.

## Architecture

1. **Layer 1: Fast Prefilter** (Regex + ChromaDB Vector Cosine Similarity) - Latency < 10ms
2. **Layer 2: XGBoost Feature Classifier** (Syntactic, Structural, and Semantic feature engineering) - Latency < 30ms
3. **Layer 3: DistilBERT Deep Classifier** (Fine-tuned sequence classification for borderline cases) - Latency < 100ms
4. **Layer 4: Pydantic Policy Validator** (Business logic and action schema constraint verification)
5. **Orchestrator**: Unified routing, dynamic escalation, and trace logging.

## Directory Structure

```
ai-firewall/
├── data/
│   ├── raw/
│   ├── processed/
│   ├── synthetic/
│   └── scripts/
├── models/
│   ├── layer1_prefilter/
│   ├── layer2_xgboost/
│   └── layer3_distilbert/
├── firewall/
├── api/
│   ├── routes/
│   ├── main.py
│   └── schemas.py
├── frontend/
│   ├── app-demo/
│   └── security-console/
├── evaluation/
├── docs/
└── tests/
```

## Quick Start

### 1. Setup Virtual Environment
```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Run Tests
```bash
pytest
```
