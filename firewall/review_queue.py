"""
Queue of actions held for a human decision (REVIEW), stored in a JSON file like the incident store.

An item is `pending` until a reviewer approves or rejects it. Approving does not run the action: the caller (the
agent runtime) reads the decision and proceeds. The queue keeps the most recent `keep` items.

The file survives a restart. Writes go to a temporary file first and replace the queue in one step, so a crash
mid-write cannot leave a half-written queue; every read and change reloads the file when another process changed it.
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
        self._mtime: Optional[float] = None
        self._load()

    def _load(self) -> None:
        """(Re)read the file when it changed since the last read or write (another process may have written it)."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self.items = json.load(handle)
            self._mtime = mtime
        except (ValueError, OSError):
            pass        # keep what is in memory rather than forget pending items over one unreadable read

    def _save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.items = self.items[-self.keep:]
        tmp = f"{self.path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.items, handle, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
        self._mtime = os.path.getmtime(self.path)

    def add(self, action_type: str, payload: Dict[str, Any], reason: str, session_id: Optional[str] = None,
            user_id: Optional[str] = None, tainted: bool = False, exposed: bool = False,
            provenance: Optional[List[Dict[str, Any]]] = None, review_by: str = "staff",
            value_provenance: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """`provenance`: the untrusted sources the session read before the action (source, chunk id), so the reviewer
        sees where an account number or an instruction may have come from. `value_provenance`: for each destination
        value of the action, whether the user typed it, untrusted content held it, or nobody did.
        `review_by`: "user" or "staff"."""
        item = {
            "id": uuid.uuid4().hex[:12], "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "pending", "action_type": action_type, "payload": payload, "reason": reason,
            "session_id": session_id, "user_id": user_id, "tainted": tainted, "exposed": exposed,
            "provenance": list(provenance or []), "value_provenance": list(value_provenance or []), "review_by": review_by,
            "reviewer": None, "decided_at": None, "note": None,
        }
        with self._lock:
            self._load()
            self.items.append(item)
            self._save()
        return item

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            rows = [i for i in self.items if status is None or i["status"] == status]
        return list(reversed(rows))

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._load()
            return next((i for i in self.items if i["id"] == item_id), None)

    def decide(self, item_id: str, approve: bool, reviewer: str, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._load()
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
