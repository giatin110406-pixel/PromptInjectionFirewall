"""
Layer 2: multilingual prompt-injection classifier (mDeBERTa-v3, trained on Colab, see models/l2_multilingual/).

A text is cut into the same overlapping windows used in training (200 tokens, stride 128) and each window is
scored; the text is an attack when ANY window reaches the threshold. That is how untrusted documents must be
scanned: an attack sentence in the middle of a long email is judged on the window that holds it, not diluted by
the rest of the text.

Contract (firewall/types.py, firewall/orchestrator.py):
  - decision BLOCK when the highest window score >= threshold, ALLOW below it;
  - two optional bands return ESCALATE for the Layer 3 judge (both off by default; the orchestrator turns them on
    only when a judge exists): `escalate_low <= score < threshold` (side "allow": let through, but only just) and
    `threshold <= score < escalate_high` (side "block": blocked, but not with confidence). Scores are bimodal, so the
    bands hold few texts; on dataset_v2 the "block" band holds about half of Layer 2's false blocks;
  - fail closed: no model, or a model that cannot run, returns REVIEW with degraded=true. There is no
    keyword fallback.

Artifacts (git-ignored, ~1.1 GB): models/l2_multilingual/artifacts/{checkpoint/, temperature.json}.
"""
import json
import os
from typing import Any, Dict, List, Optional

import numpy as np

from models.l2_multilingual.chunking import token_windows

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ARTIFACTS = os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts")
MAX_WINDOWS = 64          # a very long text keeps its first 48 and last 16 windows
MAX_SCAN_CHARS = 200_000  # same cap as Layer 1


class MultilingualClassifier:
    def __init__(self, artifacts_dir: str = DEFAULT_ARTIFACTS, device: Optional[str] = None,
                 threshold: Optional[float] = None, escalate_low: Optional[float] = None,
                 escalate_high: Optional[float] = None, batch_size: int = 32):
        self.artifacts_dir = artifacts_dir
        self.escalate_low = escalate_low
        self.escalate_high = escalate_high
        self.batch_size = batch_size
        self.model = None
        self.tokenizer = None
        self.error: Optional[str] = None
        self.temperature = 1.0
        self.threshold = 0.5
        self.max_tokens = 200
        self.stride = 128
        try:
            self._load(device, threshold)
        except Exception as exc:  # a missing or broken model is reported, never hidden
            self.model = None
            self.error = f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    def _load(self, device: Optional[str], threshold: Optional[float]) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        checkpoint = os.path.join(self.artifacts_dir, "checkpoint")
        with open(os.path.join(self.artifacts_dir, "temperature.json"), "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        self.temperature = float(cfg["temperature"])
        self.threshold = float(cfg["threshold"] if threshold is None else threshold)
        self.max_tokens = int(cfg.get("max_tokens", 200))
        self.stride = int(cfg.get("stride", 128))
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        self.model = AutoModelForSequenceClassification.from_pretrained(checkpoint).float().to(self.device).eval()

    # ------------------------------------------------------------------
    def windows(self, text: str) -> List[str]:
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
        offsets = encoded["offset_mapping"]
        spans = token_windows(len(offsets), self.max_tokens, self.stride)
        if len(spans) > MAX_WINDOWS:
            spans = spans[:MAX_WINDOWS * 3 // 4] + spans[-(MAX_WINDOWS // 4):]
        pieces = [text[offsets[a][0]:offsets[b - 1][1]] for a, b in spans]
        return [p for p in pieces if p.strip()] or [text[:2000] or " "]

    def window_scores(self, text: str) -> List[float]:
        """Attack probability of each window (temperature-scaled)."""
        return self._score_pieces(self.windows(text[:MAX_SCAN_CHARS]))

    def _score_pieces(self, pieces: List[str]) -> List[float]:
        order = sorted(range(len(pieces)), key=lambda i: len(pieces[i]))
        logits = np.zeros((len(pieces), 2), dtype=np.float32)
        torch = self._torch
        with torch.no_grad():
            for start in range(0, len(order), self.batch_size):
                idx = order[start:start + self.batch_size]
                enc = self.tokenizer([pieces[i] for i in idx], truncation=True, max_length=self.max_tokens + 16,
                                     padding=True, return_tensors="pt").to(self.device)
                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=self.device == "cuda"):
                    out = self.model(**enc).logits
                logits[idx] = out.float().cpu().numpy()
        scaled = logits / self.temperature
        scaled -= scaled.max(axis=1, keepdims=True)
        probs = np.exp(scaled) / np.exp(scaled).sum(axis=1, keepdims=True)
        return [float(p) for p in probs[:, 1]]

    # ------------------------------------------------------------------
    def check(self, text: str, top_similarity: Optional[float] = None) -> Dict[str, Any]:
        if self.model is None:
            return {"layer": 2, "decision": "REVIEW", "degraded": True, "confidence": 0.0,
                    "reason": "layer2_model_unavailable", "details": {"error": self.error}}
        pieces = self.windows(text[:MAX_SCAN_CHARS])
        scores = self._score_pieces(pieces)
        top = max(scores)
        details = {"windows": len(scores), "max_window_score": round(top, 4), "threshold": self.threshold,
                   "top_window": int(np.argmax(scores))}
        def escalate(side: str) -> Dict[str, Any]:
            # a judge should read the window that scored highest, not the whole document
            details.update(side=side, top_window_text=pieces[int(np.argmax(scores))][:1500])
            return {"layer": 2, "decision": "ESCALATE", "degraded": False, "confidence": round(top, 4),
                    "reason": f"layer2_uncertain_{side}:{top:.3f}", "details": details}

        if top >= self.threshold:
            if self.escalate_high is not None and top < self.escalate_high:
                return escalate("block")
            return {"layer": 2, "decision": "BLOCK", "degraded": False, "confidence": round(top, 4),
                    "reason": f"layer2_attack_score:{top:.3f}", "details": details}
        if self.escalate_low is not None and top >= self.escalate_low:
            return escalate("allow")
        return {"layer": 2, "decision": "ALLOW", "degraded": False, "confidence": round(1.0 - top, 4),
                "reason": f"layer2_low_risk:{top:.3f}", "details": details}
