"""
Layer 2: XGBoost Feature Classifier.
Performs classification based on 25-30 syntactic, structural, and semantic features.
Handles inputs escalated from Layer 1.
"""
import os
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
        
        # If model is not yet trained/loaded, use feature heuristic proxy
        if self.model is None:
            heuristic_score = 0.0
            if feats["override_word_count"] > 0:
                heuristic_score += 0.4
            if feats["role_claim_count"] > 0:
                heuristic_score += 0.3
            if feats["urgency_word_count"] > 0:
                heuristic_score += 0.2
            if feats["prompt_leak_cue_count"] > 0:
                heuristic_score += 0.3
            confidence = min(0.99, max(0.01, heuristic_score))
        else:
            feature_vector = [feats[name] for name in FEATURE_NAMES]
            X = pd.DataFrame([feature_vector], columns=FEATURE_NAMES)
            try:
                probs = self.model.predict_proba(X)[0]
                confidence = float(probs[1])  # probability of MALICIOUS (class 1)
            except Exception as e:
                confidence = 0.5

        if confidence >= self.block_threshold:
            decision = "BLOCK"
            reason = f"layer2_high_risk_confidence:{confidence:.3f}"
        elif confidence < self.allow_threshold:
            decision = "ALLOW"
            reason = f"layer2_low_risk_confidence:{confidence:.3f}"
        else:
            decision = "ESCALATE"  # Borderline case -> Escalated to Layer 3 DistilBERT
            reason = f"layer2_borderline_escalation:{confidence:.3f}"

        return {
            "layer": 2,
            "decision": decision,
            "confidence": round(confidence, 4),
            "reason": reason,
            "top_features": {
                k: feats[k] for k in [
                    "override_word_count", "role_claim_count", "urgency_word_count",
                    "prompt_leak_cue_count", "max_similarity"
                ]
            }
        }
