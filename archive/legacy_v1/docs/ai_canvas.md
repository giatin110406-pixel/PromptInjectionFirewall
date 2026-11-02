# AI Project Canvas: AI-Powered Threat Detection for Conversational Agents

## 1. Value Proposition
Protects conversational AI applications against prompt injection, jailbreaking, and privilege escalation with sub-50ms latency, reducing corporate risk of unauthorized data leaks and business policy circumvention.

## 2. Data Strategy
- **Raw Sources**: Public datasets (Deepset prompt injections, Kaggle adversarial benchmarks).
- **Synthetic Augmentation**: Parameterized adversarial templates covering persona claiming, urgency overrides, SQL/payload embeddings, and Vietnamese/English e-commerce customer intents.
- **Ground Truth**: 738 curated, deduplicated samples mapped to 4 taxonomy classes (`SAFE`, `INJECTION_PROMPT`, `INJECTION_PAYLOAD`, `PRIVILEGE_ESCALATION`).

## 3. Modeling & AI Architecture
- **Layer 1 (Prefilter)**: Regex keywords + Cosine similarity over known jailbreak embeddings (all-MiniLM-L6-v2 via ChromaDB).
- **Layer 2 (XGBoost)**: 25 engineered syntactic, structural, and semantic features (ROC-AUC: 0.9998, Accuracy: 98.65%).
- **Layer 3 (DistilBERT)**: Deep semantic sequence classification for ambiguous/borderline cases (confidence 0.50-0.85).
- **Layer 4 (Policy Validator)**: Pydantic v2 schemas validating outbound business actions (refund amount caps, role permissions).

## 4. Evaluation & Metrics
- **Baseline (Regex)**: Recall 36.93%, Precision 100%, F1 53.94%.
- **Layer 1 + 2 Combined**: Recall 99.09%, Precision 99.09%, F1 99.09% (+62.16% recall improvement over baseline).
- **Latency**: P95 < 2ms for Layer 1, P95 < 2ms for Layer 2, P95 < 0.02ms for Orchestrator routing.

## 5. Deployment & Integration
- **Runtime**: FastAPI REST API + WebSocket/Polling for real-time SOC incident updates.
- **Client**: Next.js demo UI (split screen: User Chat Demo on left, SOC Incident Console on right).
