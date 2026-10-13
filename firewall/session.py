"""
Per-session state kept in memory: the taint flag.

A session is TAINTED once untrusted content that carried an instruction aimed at the assistant (an email, web
page, document or tool output flagged by the context scan) has been seen in it. Layer 4 reads the flag: in a
tainted session, sensitive tools move to REVIEW and destructive ones are blocked, even when the later user
message looks harmless, because the instruction may have come from the poisoned content.

State is lost on restart and not shared between processes. It expires after `ttl_seconds` without activity.
"""
import threading
import time
from typing import Any, Dict, List, Optional

DEFAULT_TTL_SECONDS = 30 * 60


class TaintStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=time.time):
        self.ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _expire(self) -> None:
        cutoff = self._clock() - self.ttl
        for key in [k for k, v in self._sessions.items() if v["last_seen"] < cutoff]:
            del self._sessions[key]

    def mark(self, session_id: str, source: str, reason: str, chunk_id: Optional[str] = None) -> None:
        with self._lock:
            self._expire()
            state = self._sessions.setdefault(session_id, {"since": self._clock(), "events": [], "last_seen": 0.0})
            state["last_seen"] = self._clock()
            state["events"].append({"source": source, "reason": reason, "chunk_id": chunk_id, "at": self._clock()})

    def is_tainted(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        with self._lock:
            self._expire()
            return session_id in self._sessions

    def info(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            self._expire()
            state = self._sessions.get(session_id)
            if not state:
                return {"tainted": False, "events": []}
            return {"tainted": True, "since": state["since"], "events": list(state["events"])}

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)

    def tainted_sessions(self) -> List[str]:
        with self._lock:
            self._expire()
            return list(self._sessions)
