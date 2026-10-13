"""
Queue of actions held for a human decision (REVIEW), stored in a JSON file like the incident store.

An item is `pending` until a reviewer approves or rejects it. Approving does not run the action: the caller (the
agent runtime) reads the decision and proceeds. The queue keeps the most recent `keep` items.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(BASE_DIR, "data", "review_queue.json")


class ReviewQueue:
    def __init__(self, path: Optional[str] = None, keep: int = 500):
        self.path = path or os.getenv("FIREWALL_REVIEW_QUEUE") or DEFAULT_PATH
        self.keep = keep
        self._lock = threading.Lock()
        self.items: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    self.items = json.load(handle)
            except (ValueError, OSError):
                self.items = []

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.items[-self.keep:], handle, indent=2, ensure_ascii=False)

    def add(self, action_type: str, payload: Dict[str, Any], reason: str, session_id: Optional[str] = None,
            user_id: Optional[str] = None, tainted: bool = False) -> Dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex[:12], "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "pending", "action_type": action_type, "payload": payload, "reason": reason,
            "session_id": session_id, "user_id": user_id, "tainted": tainted,
            "reviewer": None, "decided_at": None, "note": None,
        }
        with self._lock:
            self.items.append(item)
            self._save()
        return item

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = [i for i in self.items if status is None or i["status"] == status]
        return list(reversed(rows))

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((i for i in self.items if i["id"] == item_id), None)

    def decide(self, item_id: str, approve: bool, reviewer: str, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = next((i for i in self.items if i["id"] == item_id), None)
            if item is None or item["status"] != "pending":
                return None
            item.update(status="approved" if approve else "rejected", reviewer=reviewer, note=note,
                        decided_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self._save()
            return dict(item)

    def clear(self) -> None:
        with self._lock:
            self.items = []
            self._save()
