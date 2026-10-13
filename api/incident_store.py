"""
In-memory & JSON-backed Incident Store for SOC Security Console.
"""
import os
import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCIDENTS_FILE = os.path.join(BASE_DIR, "data", "incidents.json")

class IncidentStore:
    def __init__(self):
        self.incidents: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if os.path.exists(INCIDENTS_FILE):
            try:
                with open(INCIDENTS_FILE, "r", encoding="utf-8") as f:
                    self.incidents = json.load(f)
            except Exception:
                self.incidents = []

    def _save(self):
        os.makedirs(os.path.dirname(INCIDENTS_FILE), exist_ok=True)
        try:
            with open(INCIDENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.incidents[-200:], f, indent=2)  # retain last 200 incidents
        except Exception as e:
            print(f"[WARN] Failed to save incidents: {e}")

    def log_incident(
        self,
        input_text: str,
        blocked_by_layer: int,
        reason: str,
        confidence: float,
        total_latency_ms: float,
        trace: List[Dict[str, Any]],
        session_id: str = "default",
        user_id: str = "anon",
        decision: str = "BLOCK",
    ) -> Dict[str, Any]:
        incident = {
            "id": f"inc_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "input_text": input_text,
            "blocked_by_layer": blocked_by_layer,
            "decision": decision,
            "reason": reason,
            "confidence": round(confidence, 4),
            "total_latency_ms": round(total_latency_ms, 2),
            "trace": trace
        }
        self.incidents.insert(0, incident)  # newest first
        self._save()
        return incident

    def get_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.incidents[:limit]

    def get_stats(self) -> Dict[str, Any]:
        total = len(self.incidents)
        layer_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        decision_counts = {"BLOCK": 0, "REVIEW": 0, "SANITIZE": 0}
        for inc in self.incidents:
            layer = inc.get("blocked_by_layer", 1)
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
            decision = inc.get("decision", "BLOCK")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

        avg_latency = (
            sum(inc.get("total_latency_ms", 0.0) for inc in self.incidents) / max(total, 1)
        )
        return {
            "total_incidents": total,
            "by_layer": layer_counts,
            "by_decision": decision_counts,
            "avg_latency_ms": round(avg_latency, 2)
        }

# Global singleton
incident_store = IncidentStore()
