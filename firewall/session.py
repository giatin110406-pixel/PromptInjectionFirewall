"""
Per-session state kept in memory: the exposure and taint flags.

Two levels, the second implies the first:
  EXPOSED  the session has read untrusted content (an email, web page, document or tool output sent through the
           context scan), whatever the scan found. Nothing in the firewall can prove that content held no instruction:
           a well-written attack passes every text filter. Layer 4 reads the flag and asks for a confirmation before a
           sensitive action (`when_exposed` in policies.yaml), so the protection does not depend on the detection.
  TAINTED  one of those chunks carried an instruction a healthy layer was sure about. Layer 4 reacts harder
           (`when_tainted`): destructive actions are blocked, even when the later user message looks harmless,
           because the instruction may have come from the poisoned content.

State is in memory and expires after `ttl_seconds` without activity. With a `StateStore` (firewall/state_store.py,
switched on by FIREWALL_STATE_DB) every change is also written to SQLite and every read reloads the session's row, so
the state survives a restart and is shared between processes.
"""
import threading
import time
from typing import Any, Dict, List, Optional

from firewall.state_store import StateStore

DEFAULT_TTL_SECONDS = 30 * 60
MAX_EXPOSURE_EVENTS = 50          # a long session reading many documents keeps its most recent sources

CLEAN, EXPOSED, TAINTED = "clean", "exposed", "tainted"
NAMESPACE = "session"


class TaintStore:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=time.time, store: Optional[StateStore] = None):
        self.ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._store = store
        self._sessions: Dict[str, Dict[str, Any]] = {}       # tainted sessions
        self._exposed: Dict[str, Dict[str, Any]] = {}        # exposed sessions (a tainted session is exposed too)

    def _expire(self) -> None:
        cutoff = self._clock() - self.ttl
        for store in (self._sessions, self._exposed):
            for key in [k for k, v in store.items() if v["last_seen"] < cutoff]:
                del store[key]
        if self._store is not None:
            self._store.delete_older(NAMESPACE, cutoff)

    # ---- durable copy (no-ops without a StateStore); callers hold the lock
    def _sync(self, session_id: str) -> None:
        if self._store is None:
            return
        row = self._store.get(NAMESPACE, session_id) or {}
        for memory, part in ((self._sessions, "tainted"), (self._exposed, "exposed")):
            if row.get(part):
                memory[session_id] = row[part]
            else:
                memory.pop(session_id, None)

    def _sync_all(self) -> None:
        if self._store is None:
            return
        self._sessions.clear()
        self._exposed.clear()
        for key, row in self._store.items(NAMESPACE):
            if row.get("tainted"):
                self._sessions[key] = row["tainted"]
            if row.get("exposed"):
                self._exposed[key] = row["exposed"]

    def _persist(self, session_id: str) -> None:
        if self._store is None:
            return
        tainted, exposed = self._sessions.get(session_id), self._exposed.get(session_id)
        if tainted is None and exposed is None:
            self._store.delete(NAMESPACE, session_id)
            return
        seen = max(s["last_seen"] for s in (tainted, exposed) if s is not None)
        self._store.put(NAMESPACE, session_id, {"tainted": tainted, "exposed": exposed}, seen)

    def _expose_locked(self, session_id: str, event: Dict[str, Any]) -> None:
        state = self._exposed.setdefault(session_id, {"since": self._clock(), "events": [], "last_seen": 0.0})
        state["last_seen"] = self._clock()
        state["events"].append(event)
        del state["events"][:-MAX_EXPOSURE_EVENTS]

    def expose(self, session_id: str, source: str, chunk_id: Optional[str] = None, decision: Optional[str] = None,
               risk: Optional[float] = None) -> None:
        """The session read one untrusted chunk. `decision` is what the scan said about it (for the console);
        `risk` is the chunk's highest Layer 2 score (Layer 4 reads the session maximum, see `exposure_risk`)."""
        with self._lock:
            self._expire()
            self._sync(session_id)
            self._expose_locked(session_id, {"source": source, "chunk_id": chunk_id, "decision": decision,
                                             "risk": risk, "at": self._clock()})
            self._persist(session_id)

    def mark(self, session_id: str, source: str, reason: str, chunk_id: Optional[str] = None) -> None:
        with self._lock:
            self._expire()
            self._sync(session_id)
            state = self._sessions.setdefault(session_id, {"since": self._clock(), "events": [], "last_seen": 0.0})
            state["last_seen"] = self._clock()
            state["events"].append({"source": source, "reason": reason, "chunk_id": chunk_id, "at": self._clock()})
            self._expose_locked(session_id, {"source": source, "chunk_id": chunk_id, "decision": "BLOCK",
                                             "risk": 1.0, "at": self._clock()})
            self._persist(session_id)

    def is_tainted(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        with self._lock:
            self._expire()
            self._sync(session_id)
            return session_id in self._sessions

    def is_exposed(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        with self._lock:
            self._expire()
            self._sync(session_id)
            return session_id in self._exposed

    def level(self, session_id: Optional[str]) -> str:
        if not session_id:
            return CLEAN
        with self._lock:
            self._expire()
            self._sync(session_id)
            if session_id in self._sessions:
                return TAINTED
            return EXPOSED if session_id in self._exposed else CLEAN

    def exposure_sources(self, session_id: Optional[str]) -> List[Dict[str, Any]]:
        """Where the untrusted content of the session came from, oldest first (source and chunk id)."""
        if not session_id:
            return []
        with self._lock:
            self._expire()
            self._sync(session_id)
            state = self._exposed.get(session_id)
            return [{"source": e["source"], "chunk_id": e["chunk_id"]} for e in state["events"]] if state else []

    def exposure_risk(self, session_id: Optional[str]) -> float:
        """Highest Layer 2 score among the untrusted chunks the session read (0.0 when none or not scored)."""
        if not session_id:
            return 0.0
        with self._lock:
            self._expire()
            self._sync(session_id)
            state = self._exposed.get(session_id)
            return max((float(e.get("risk") or 0.0) for e in state["events"]), default=0.0) if state else 0.0

    def info(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            self._expire()
            self._sync(session_id)
            exposed = self._exposed.get(session_id)
            out = {"exposed": exposed is not None, "exposure_events": list(exposed["events"]) if exposed else []}
            state = self._sessions.get(session_id)
            if not state:
                return dict(out, tainted=False, events=[], level=EXPOSED if exposed else CLEAN)
            return dict(out, tainted=True, since=state["since"], events=list(state["events"]), level=TAINTED)

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            for store in (self._sessions, self._exposed):
                if session_id is None:
                    store.clear()
                else:
                    store.pop(session_id, None)
            if self._store is not None:
                self._store.delete(NAMESPACE, session_id)

    def tainted_sessions(self) -> List[str]:
        with self._lock:
            self._expire()
            self._sync_all()
            return list(self._sessions)

    def exposed_sessions(self) -> List[str]:
        with self._lock:
            self._expire()
            self._sync_all()
            return list(self._exposed)
