"""A small, separately locked event buffer readable while Agent.run owns its session."""
import threading
import time
import uuid


class ProgressTracker:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = []
        self.running = False
        self.started = None
        self.run_id = None
        self.current = None
        self.counter = 0

    def start(self, text):
        with self.lock:
            self.events = []
            self.counter = 0
            self.started = time.monotonic()
            self.run_id = uuid.uuid4().hex[:12]
            self.running = True
            self.current = None
            self.emit({"stage": "INPUT", "phase": "input", "state": "running", "preview": text[:300]})

    def emit(self, event):
        with self.lock:
            self.counter += 1
            entry = {**event, "id": self.counter,
                     "elapsed_ms": round((time.monotonic() - self.started) * 1000, 1) if self.started else 0}
            self.events.append(entry)
            self.events = self.events[-240:]
            self.current = entry

    def finish(self, decision, error=None, error_code=None):
        with self.lock:
            if not self.running:
                return
            stage = (self.current or {}).get("stage", "INPUT")
            self.emit({"stage": stage, "phase": (self.current or {}).get("phase", "input"),
                       "state": "error" if error else "finished", "decision": decision,
                       "message": error, "error_code": error_code})
            self.running = False

    def snapshot(self, after=0):
        with self.lock:
            return {"run_id": self.run_id, "running": self.running, "current": dict(self.current) if self.current else None,
                    "cursor": self.counter, "events": [dict(event) for event in self.events if event["id"] > after],
                    "truncated": bool(self.events and after and after < self.events[0]["id"] - 1)}
