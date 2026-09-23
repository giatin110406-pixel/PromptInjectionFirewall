# AI System Card: AI-Powered Threat Detection Firewall

## 1. System Overview
- **System Name**: AI Firewall for Conversational Agents
- **Version**: 1.0.0 (MVP)
- **Primary Function**: Intercepts and filters malicious inputs (Prompt Injections, Jailbreak attacks, Privilege Escalations) and enforces outbound business logic guards before requests reach conversational LLMs or backend tools.

## 2. Architecture & Components
1. **Layer 1 (Regex & Vector Prefilter)**: Rapid signature matching + ChromaDB cosine similarity.
2. **Layer 2 (XGBoost Classifier)**: 25-feature structural/syntactic gradient boosted classifier.
3. **Layer 3 (DistilBERT Classifier)**: Borderline semantic resolution for complex roleplay scenarios.
4. **Layer 4 (Pydantic Policy Validator)**: Enforces business logic rules (e.g., maximum refund amounts, role privilege gates).
5. **Orchestrator**: Dynamic escalation engine with transparent multi-layer trace output.

## 3. Quantitative Performance
- **Baseline Recall**: 36.93% (F1: 53.94%)
- **Layer 2 Model ROC-AUC**: 0.9998
- **Layer 1 + 2 Combined Recall**: 99.09% (F1: 99.09%)
- **Improvement over Baseline**: +62.16% recall gain
- **Latency Profile**:
  - Baseline (Regex): P95 = 0.013 ms
  - Layer 1 (Prefilter): P95 = 0.014 ms
  - Layer 2 (XGBoost): P95 = 1.819 ms
  - Layer 4 (Policy): P95 = 0.005 ms
  - End-to-End Orchestrator: P95 = 0.017 ms

## 4. Intended Use & Boundaries
- **Intended Use**: Customer service chatbots, enterprise internal copilots, autonomous agent workflows.
- **Out of Scope**: Multimodal image/audio analysis, operating system kernel packet inspection.
