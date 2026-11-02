# Risk Register: AI Firewall System

| Risk ID | Category | Risk Description | Likelihood | Impact | Mitigation Strategy | Status |
|---|---|---|---|---|---|---|
| R-01 | Latency | Heavy neural models (e.g. DistilBERT / LLM) exceed latency budget (>100ms) on CPU | High | High | Tiered escalation architecture: >80% traffic filtered by Layer 1 & 2 in < 2ms; DistilBERT only invoked on borderline confidence (0.50-0.85) | Mitigated |
| R-02 | Accuracy | High false positive rate blocks legitimate user complaints or refund requests | Medium | High | Separate Feature Classifier (Layer 2) with high decision threshold (0.85) and fallback Layer 4 action validation | Mitigated |
| R-03 | Robustness | Novel zero-day jailbreak tokens (e.g. leetspeak, ASCII art, Base64 smuggling) bypass regex | High | Medium | Vector semantic search + structural feature extraction (Base64 cue flags, character entropy, delimiter ratios) | Mitigated |
| R-04 | Business Logic | Prompt injection forces agent to invoke unauthorized refund tool with large sums | High | Critical | Layer 4 Pydantic policy validator strictly enforces role limits and order value caps (max 110%) at runtime | Mitigated |
| R-05 | Availability | ChromaDB or HuggingFace offline during initialization | Medium | Low | Graceful degradation implemented: Layer 1, 2, and 4 continue functioning independently with local heuristics | Mitigated |
