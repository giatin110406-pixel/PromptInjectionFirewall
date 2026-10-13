"""
Feedback from people using the console: "this block was wrong" (false_positive) or "this attack got through" (missed_attack).

Each report is one JSON line in data/feedback/feedback.jsonl (override with FIREWALL_FEEDBACK_FILE). It is NOT an allow-list:
a reported text is never let through automatically. The file feeds the next training round (hard negatives for false
positives, attacks for misses) and a regression check (data/scripts/feedback_report.py --recheck).
"""
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(BASE_DIR, "data", "feedback", "feedback.jsonl")
KINDS = ("false_positive", "missed_attack")


def text_hash(text: str) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", text.strip().lower()).encode("utf-8")).hexdigest()[:12]


class FeedbackStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("FIREWALL_FEEDBACK_FILE") or DEFAULT_PATH
        self._lock = threading.Lock()

    def _read(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        rows = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        return rows

    def add(self, kind: str, text: str, mode: str = "message", decision: str = "", layer: Optional[int] = None,
            reason: str = "", note: str = "", user: str = "", session_id: str = "") -> Dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        item = {"id": "fb_" + text_hash(kind + text), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "kind": kind, "text": text, "text_hash": text_hash(text), "mode": mode, "decision": decision,
                "layer": layer, "reason": reason[:300], "note": note[:500], "user": user, "session_id": session_id}
        with self._lock:
            if any(r.get("id") == item["id"] for r in self._read()):
                return dict(item, duplicate=True)         # the same report is not stored twice
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return dict(item, duplicate=False)

    def list(self, limit: int = 100, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [r for r in self._read() if kind is None or r.get("kind") == kind]
        return list(reversed(rows))[:limit]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            rows = self._read()
        return {kind: sum(1 for r in rows if r.get("kind") == kind) for kind in KINDS}


feedback_store = FeedbackStore()
