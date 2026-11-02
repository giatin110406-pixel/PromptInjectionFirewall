"""
Firewall Orchestrator: Multi-Layer Threat Detection Pipeline.
Coordinates Layer 1 (Prefilter), Layer 2 (XGBoost), Layer 3 (DistilBERT),
and Layer 4 (Policy Validator), producing a transparent execution trace.
"""
import time
from typing import Dict, Any, List, Optional
from firewall.layer1 import Layer1Prefilter
from firewall.layer2 import Layer2Classifier
from firewall.layer3 import Layer3Classifier
from firewall.layer4 import Layer4Validator

class FirewallOrchestrator:
    def __init__(
        self,
        layer1: Optional[Layer1Prefilter] = None,
        layer2: Optional[Layer2Classifier] = None,
        layer3: Optional[Layer3Classifier] = None,
        layer4: Optional[Layer4Validator] = None,
    ):
        self.layer1 = layer1 or Layer1Prefilter()
        self.layer2 = layer2 or Layer2Classifier()
        self.layer3 = layer3 or Layer3Classifier()
        self.layer4 = layer4 or Layer4Validator()

    def process_input(self, text: str) -> Dict[str, Any]:
        """
        Processes prompt text through the defense layers with dynamic escalation.
        Returns:
            dict: {
                "decision": "ALLOW" | "BLOCK",
                "stopped_at_layer": int,
                "final_reason": str,
                "total_latency_ms": float,
                "trace": list[dict]
            }
        """
        start_total = time.perf_counter()
        trace: List[Dict[str, Any]] = []

        # ---------------- LAYER 1: Fast Prefilter ----------------
        t0 = time.perf_counter()
        r1 = self.layer1.check(text)
        r1["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        trace.append(r1)

        if r1["decision"] == "BLOCK":
            return self._build_response("BLOCK", 1, r1["reason"], trace, start_total)

        # ---------------- LAYER 2: XGBoost Feature Classifier ----------------
        t1 = time.perf_counter()
        top_sim = r1.get("confidence", 0.0)
        r2 = self.layer2.check(text, top_similarity=top_sim)
        r2["latency_ms"] = round((time.perf_counter() - t1) * 1000, 2)
        trace.append(r2)

        if r2["decision"] == "BLOCK":
            return self._build_response("BLOCK", 2, r2["reason"], trace, start_total)
        elif r2["decision"] == "ALLOW":
            return self._build_response("ALLOW", 2, r2["reason"], trace, start_total)

        # ---------------- LAYER 3: DistilBERT Deep Classifier ----------------
        t2 = time.perf_counter()
        r3 = self.layer3.check(text)
        r3["latency_ms"] = round((time.perf_counter() - t2) * 1000, 2)
        trace.append(r3)

        decision = "BLOCK" if r3["decision"] == "BLOCK" else "ALLOW"
        return self._build_response(decision, 3, r3["reason"], trace, start_total)

    def validate_action(self, action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validates outbound agent action requests via Layer 4."""
        t0 = time.perf_counter()
        res = self.layer4.validate_action(action_type, payload)
        res["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return res

    def _build_response(
        self,
        decision: str,
        stopped_at_layer: int,
        reason: str,
        trace: List[Dict[str, Any]],
        start_total: float,
    ) -> Dict[str, Any]:
        total_ms = round((time.perf_counter() - start_total) * 1000, 2)
        return {
            "decision": decision,
            "stopped_at_layer": stopped_at_layer,
            "final_reason": reason,
            "total_latency_ms": total_ms,
            "trace": trace
        }
