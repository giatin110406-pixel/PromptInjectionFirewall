"""
Layer 3: Deep Classifier (Multilingual Transformer / DistilBERT).
Specialized for ambiguous, borderline, roleplay, and multi-step inputs
escalated from Layer 2, with full support for both English and Vietnamese.
"""
import os
from typing import Dict, Any, Optional
from data.scripts.vietnamese_norm import clean_text

class Layer3Classifier:
    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        threshold: float = 0.60,
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
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                self.tokenizer = AutoTokenizer.from_pretrained(self.checkpoint_path)
                self.model = AutoModelForSequenceClassification.from_pretrained(self.checkpoint_path)
                self.model.eval()
                if torch.cuda.is_available():
                    self.model.to("cuda")
            except Exception as e:
                print(f"[WARN] Could not load Layer 3 checkpoint ({e}). Running in fallback mode.")
                self.model = None
                self.tokenizer = None

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

        norm_text = clean_text(text)

        subtle_indicators = [
            # English indicators
            "hypothetically", "fictional", "novel", "educational purpose only",
            "for research", "research paper", "movie script", "pretend you are", "roleplay",
            "simulation mode", "without any restrictions", "unbounded",
            "exploit mechanism", "scada", "malware", "industrial control", "step-by-step",
            # Vietnamese indicators
            "giả thuyết", "gia thuyet", "tiểu thuyết", "tieu thuyet",
            "mục đích giáo dục", "muc dich giao duc", "nghiên cứu bảo mật", "nghien cuu bao mat",
            "kịch bản phim", "kich ban phim", "đóng vai", "dong vai",
            "chế độ mô phỏng", "che do mo phong", "không có bất kỳ giới hạn nào", "khong co bat ky gioi han nao",
            "cơ chế khai thác", "co che khai thac", "mã độc", "ma doc",
            "từng bước", "tung buoc", "chỉ dẫn ẩn", "chi dan an", "tài liệu yêu cầu", "tai lieu yeu cau"
        ]
        lower_text = norm_text.lower()
        hit_count = sum(1 for ind in subtle_indicators if ind in lower_text)
        heuristic_prob = min(0.95, 0.45 + (hit_count * 0.20)) if hit_count > 0 else 0.25

        if self.model is not None and self.tokenizer is not None:
            import torch
            device = next(self.model.parameters()).device
            inputs = self.tokenizer(
                norm_text,
                return_tensors="pt",
                truncation=True,
                max_length=256,
                return_token_type_ids=False,
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                model_prob = float(probs[0][1].detach().cpu().item())

            # Hybrid defense: reinforce model confidence when strong exploit indicators are matched
            if hit_count >= 2:
                malicious_prob = max(model_prob, heuristic_prob)
            elif hit_count == 1:
                malicious_prob = max(model_prob, 0.5 * model_prob + 0.5 * heuristic_prob)
            else:
                malicious_prob = model_prob
        else:
            # Fail closed: without the trained model there is no valid score. Do not
            # substitute the keyword heuristic; hand the decision to a human.
            return {
                "layer": 3,
                "decision": "REVIEW",
                "confidence": 0.0,
                "reason": "layer3_model_unavailable",
                "degraded": True,
            }

        decision = "BLOCK" if malicious_prob >= self.threshold else "ALLOW"
        reason = f"layer3_deep_classifier_score:{malicious_prob:.3f}"

        return {
            "layer": 3,
            "decision": decision,
            "confidence": round(malicious_prob, 4),
            "reason": reason
        }
