"""
Layer 3: DistilBERT Deep Classifier.
Specialized for ambiguous, borderline, roleplay, and multi-step inputs
escalated from Layer 2.
"""
import os
from typing import Dict, Any, Optional

class Layer3Classifier:
    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        threshold: float = 0.65,
    ):
        self.threshold = threshold
        if checkpoint_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            checkpoint_path = os.path.join(base_dir, "models", "layer3_distilbert", "checkpoint")
        self.checkpoint_path = checkpoint_path
        self.tokenizer = None
        self.model = None
        self._load_model()

    def _load_model(self):
        if os.path.exists(self.checkpoint_path):
            try:
                import torch
                from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
                self.tokenizer = DistilBertTokenizer.from_pretrained(self.checkpoint_path)
                self.model = DistilBertForSequenceClassification.from_pretrained(self.checkpoint_path)
                self.model.eval()
            except Exception as e:
                print(f"[WARN] Could not load DistilBERT checkpoint ({e}). Running in fallback mode.")
                self.model = None

    def check(self, text: str) -> Dict[str, Any]:
        """
        Deep sequence classification of borderline cases.
        Returns:
            dict: { "layer": 3, "decision": "BLOCK" | "ALLOW", "confidence": float, "reason": str }
        """
        if not text or not isinstance(text, str):
            return {
                "layer": 3,
                "decision": "ALLOW",
                "confidence": 0.0,
                "reason": "empty_input"
            }

        if self.model is not None and self.tokenizer is not None:
            import torch
            inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                malicious_prob = float(probs[0][1].item())
        else:
            # Fallback semantic heuristic for borderline cases
            # Checks for multi-step reasoning, hypothetical framing, obfuscation
            subtle_indicators = [
                "hypothetically", "fictional", "novel", "educational purpose only",
                "for research", "movie script", "pretend you are", "roleplay",
                "simulation mode", "without any restrictions", "unbounded"
            ]
            lower_text = text.lower()
            hit_count = sum(1 for ind in subtle_indicators if ind in lower_text)
            malicious_prob = min(0.95, 0.45 + (hit_count * 0.20)) if hit_count > 0 else 0.25

        decision = "BLOCK" if malicious_prob >= self.threshold else "ALLOW"
        reason = f"layer3_distilbert_score:{malicious_prob:.3f}"

        return {
            "layer": 3,
            "decision": decision,
            "confidence": round(malicious_prob, 4),
            "reason": reason
        }
