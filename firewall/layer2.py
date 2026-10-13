"""
Layer 2: XGBoost Feature Classifier.
Performs classification based on 32 syntactic, structural, and semantic features.
Supports both English and Vietnamese prompts and escalates borderline inputs to Layer 3.
"""
import os
import re
import joblib
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from models.layer2_xgboost.features import extract_features, FEATURE_NAMES

class Layer2Classifier:
    def __init__(
        self,
        model_path: Optional[str] = None,
        block_threshold: float = 0.85,
        allow_threshold: float = 0.50,
    ):
        self.block_threshold = block_threshold
        self.allow_threshold = allow_threshold
        
        if model_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, "models", "layer2_xgboost", "model.pkl")
            
        self.model_path = model_path
        self.model = None
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
            except Exception as e:
                print(f"[WARN] Failed to load Layer 2 model from {self.model_path}: {e}")
                self.model = None

    def check(self, text: str, top_similarity: float = 0.0) -> Dict[str, Any]:
        """
        Extract features and classify text using the trained XGBoost model.
        Returns:
            dict: {
                "layer": 2,
                "decision": "BLOCK" | "ALLOW" | "ESCALATE",
                "confidence": float,
                "reason": str,
                "features": dict
            }
        """
        feats = extract_features(text, top_similarity=top_similarity)

        # Route semantic, indirect, or complex exploits to Layer 3.
        # Layer 2 is a fast feature filter and should not make a final allow decision when
        # the prompt asks for a detailed exploit or embeds an instruction in a document.
        subtle_escalation = bool(re.search(
            r"(step[- ]by[- ]step|detailed\s+technical|exploit\s+mechanism|"
            r"bypass.*industrial\s+control|malware|ransomware|stuxnet|ics|scada|"
            r"hidden\s+instruction|retrieved\s+(document|article|webpage)|"
            r"document\s+(asks|instructs)|email\s+(asks|instructs)|"
            r"từng\s+bước|tung\s+buoc|hướng\s+dẫn\s+chi\s+tiết|mã\s+độc|ma\s+doc|"
            r"tống\s+tiền|chỉ\s+dẫn\s+ẩn|văn\s+bản\s+đính\s+kèm)",
            text,
            re.IGNORECASE,
        ))
        
        # If model is not yet trained/loaded, use feature heuristic proxy
        if self.model is None:
            heuristic_score = 0.0
            if feats["override_word_count"] > 0 or feats["privilege_phrase_count_vi"] > 0:
                heuristic_score += 0.4
            if feats["role_claim_count"] > 0 or feats["vietnamese_role_claim_count"] > 0:
                heuristic_score += 0.3
            if feats["urgency_word_count"] > 0 or feats["urgency_phrase_count_vi"] > 0:
                heuristic_score += 0.2
            if feats["prompt_leak_cue_count"] > 0 or feats["vietnamese_prompt_leak_count"] > 0:
                heuristic_score += 0.3
            if feats["vietnamese_action_abuse_count"] > 0:
                heuristic_score += 0.2
            confidence = min(0.99, max(0.01, heuristic_score))
        else:
            feature_vector = [feats[name] for name in FEATURE_NAMES]
            X = pd.DataFrame([feature_vector], columns=FEATURE_NAMES)
            try:
                probs = self.model.predict_proba(X)[0]
                confidence = float(probs[1])  # probability of MALICIOUS (class 1)
            except Exception as e:
                confidence = 0.5

        # Form-only signals such as length and punctuation must not block a
        # normal support question. Require at least one attack-oriented cue for
        # a high-confidence model prediction to become a Layer 2 block.
        attack_cue_count = sum(
            feats[name] > 0 for name in [
                "role_claim_count", "urgency_word_count", "override_word_count",
                "prompt_leak_cue_count", "sql_keyword_count", "has_code_block",
                "has_delimiter_injection", "has_base64_cue", "has_url_or_path",
                "vietnamese_role_claim_count", "urgency_phrase_count_vi",
                "privilege_phrase_count_vi", "vietnamese_prompt_leak_count",
                "vietnamese_action_abuse_count"
            ]
        )
        attack_cue_count += int(bool(re.search(
            r"\b(jailbreak|prompt\s+injection|system\s+prompt|safety\s+guardrail|bỏ\s+qua|vượt\s+quyền|quản\s+trị\s+viên)\b",
            text,
            re.IGNORECASE,
        )))
        if attack_cue_count == 0 and confidence >= self.allow_threshold:
            confidence = min(confidence, self.allow_threshold - 0.01)

        if subtle_escalation:
            decision = "ESCALATE"
            reason = "layer2_semantic_routing_to_layer3"
        elif confidence >= self.block_threshold:
            decision = "BLOCK"
            reason = f"layer2_high_risk_confidence:{confidence:.3f}"
        elif confidence < self.allow_threshold:
            decision = "ALLOW"
            reason = f"layer2_low_risk_confidence:{confidence:.3f}"
        else:
            decision = "ESCALATE"  # Borderline case -> Escalated to Layer 3
            reason = f"layer2_borderline_escalation:{confidence:.3f}"

        return {
            "layer": 2,
            "decision": decision,
            "confidence": round(confidence, 4),
            "reason": reason,
            # No trained model: the score above is a keyword heuristic, so the
            # orchestrator must not treat an ALLOW from this layer as final.
            "degraded": self.model is None,
            "top_features": {
                k: feats[k] for k in [
                    "override_word_count", "role_claim_count", "urgency_word_count",
                    "prompt_leak_cue_count", "privilege_phrase_count_vi", "max_similarity"
                ] if k in feats
            }
        }
