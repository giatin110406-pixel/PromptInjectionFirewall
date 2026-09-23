# Project Charter: AI-Powered Threat Detection for Conversational Agents (AI Firewall)

## 1. Executive Summary
Conversational AI agents deployed in customer support, financial services, and internal operations are increasingly vulnerable to prompt injections, goal hijacking, jailbreaking, and unauthorized privilege escalation. Traditional static regex filters suffer from low recall (<40%), while querying large language models (LLMs) to inspect every incoming prompt introduces prohibitive latency (>500ms) and inference costs.

This project delivers a high-throughput, multi-layered AI Firewall MVP combining regex prefiltering, semantic vector similarity, gradient-boosted feature classification (XGBoost), sequence classification (DistilBERT), and Pydantic policy guards.

## 2. Objectives & Success Criteria
- **Latency Target**: P95 end-to-end inspection latency < 50ms (achieved P95 < 2ms for Layers 1 & 2).
- **Recall Target**: Detect > 90% of malicious prompt injections (demonstrated > 98% recall with Layer 2 vs. 36.9% baseline).
- **Zero Disruption for Benign Traffic**: Precision > 97% on genuine customer service prompts.
- **Explainability**: Transparent 4-layer trace logged for SOC security analysts.

## 3. Scope
- **In-Scope**:
  - Layer 1: Regex & Vector Prefilter (<10ms)
  - Layer 2: XGBoost Feature Classifier (<30ms)
  - Layer 3: DistilBERT Borderline Sequence Classifier (<100ms)
  - Layer 4: Pydantic Policy Validator for business actions (<5ms)
  - Orchestrator engine with dynamic escalation
  - FastAPI inference and security incident dashboard routes
  - Demo interface and real-time SOC incident console
- **Out-of-Scope**:
  - Continuous distributed model training clusters
  - Voice/audio multimodal filtering

## 4. Key Milestones (Mapped to 4 Sprints)
- **Sprint 1 (Tuần 2-3)**: Repo scaffolding, raw & synthetic datasets, ground truth taxonomy, regex baseline evaluation.
- **Sprint 2 (Tuần 4-5)**: Layer 1 vector prefilter + Layer 2 XGBoost feature classifier (AUC > 0.75 target achieved).
- **Sprint 3 (Tuần 6-7)**: Layer 3 DistilBERT + Layer 4 Pydantic policy validator + unified Orchestrator + FastAPI backend.
- **Sprint 4 (Tuần 8-9)**: Next.js frontend demo, real-time incident monitor, demo scenarios, final AI System Card.
