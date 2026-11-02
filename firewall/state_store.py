"""
Durable session state (WP10): a small SQLite key-value table shared by the per-session stores.

Without it the exposure/taint flags (firewall/session.py), the values the user typed (firewall/values.py) and the
canary tokens (firewall/output_guard.py) live in RAM: a restart forgets that a session read a poisoned email, and two
API processes do not see each other's sessions. With it every change is written through, and every read of a session
reloads that session's row, so a restarted or second process sees the same state.

Switched on by the environment variable FIREWALL_STATE_DB (a file path; run_demo.bat sets one). Unset, the stores stay
in memory as before: tests and evaluations build many engines and must not share sessions through a file.

Table: state(namespace, key, value JSON, updated_at). `updated_at` comes from the caller's clock, so the stores keep
their own expiry rule (ttl) and tests can drive it with a fake clock.
"""
import json
import os
import sqlite3
import threading
from typing import Any, Dict, Iterator, Optional, Tuple

ENV_VAR = "FIREWALL_STATE_DB"


class StateStore:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=5.0, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._db.execute("CREATE TABLE IF NOT EXISTS state (namespace TEXT NOT NULL, key TEXT NOT NULL, "
                         "value TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (namespace, key))")

    @classmethod
    def from_env(cls) -> Optional["StateStore"]:
        path = os.getenv(ENV_VAR, "").strip()
        return cls(path) if path else None

    def get(self, namespace: str, key: str) -> Optional[Any]:
        with self._lock:
            row = self._db.execute("SELECT value FROM state WHERE namespace = ? AND key = ?", (namespace, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, namespace: str, key: str, value: Any, updated_at: float) -> None:
        text = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._db.execute("INSERT INTO state (namespace, key, value, updated_at) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT(namespace, key) DO UPDATE SET value = excluded.value, "
                             "updated_at = excluded.updated_at", (namespace, key, text, updated_at))

    def delete(self, namespace: str, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._db.execute("DELETE FROM state WHERE namespace = ?", (namespace,))
            else:
                self._db.execute("DELETE FROM state WHERE namespace = ? AND key = ?", (namespace, key))

    def delete_older(self, namespace: str, cutoff: float) -> None:
        with self._lock:
            self._db.execute("DELETE FROM state WHERE namespace = ? AND updated_at < ?", (namespace, cutoff))

    def items(self, namespace: str) -> Iterator[Tuple[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM state WHERE namespace = ?", (namespace,)).fetchall()
        for key, value in rows:
            yield key, json.loads(value)

    def count(self, namespace: str) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM state WHERE namespace = ?", (namespace,)).fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            rows = self._db.execute("SELECT namespace, COUNT(*) FROM state GROUP BY namespace").fetchall()
        return {"path": self.path, "rows": dict(rows)}
