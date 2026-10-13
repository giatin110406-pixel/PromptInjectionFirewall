"""
Firewall Orchestrator: Multi-Layer Threat Detection Pipeline.
Coordinates Layer 1 (Prefilter), Layer 2 (Feature classifier), Layer 3 (Deep
classifier) and Layer 4 (Policy Validator), producing a transparent trace.

Contract (see firewall/types.py):
- Final decisions are ALLOW / SANITIZE / REVIEW / BLOCK. When layers disagree the
  most severe one wins.
- Fail closed: a layer that ran without a valid model (`degraded=true`) or that
  raised an error can never produce a final ALLOW. The request becomes REVIEW.
"""
import time
from typing import Any, Callable, Dict, List, Optional

from firewall.layer1 import Layer1Prefilter
from firewall.layer2 import Layer2Classifier
from firewall.layer3 import Layer3Classifier
from firewall.layer4 import Layer4Validator
from firewall.types import Decision, LayerResult, max_decision, parse_decision


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
                "decision": "ALLOW" | "SANITIZE" | "REVIEW" | "BLOCK",
                "stopped_at_layer": int,
                "final_reason": str,
                "total_latency_ms": float,
                "degraded": bool,
                "degraded_layers": list[int],
                "trace": list[dict]
            }
        """
        start_total = time.perf_counter()
        trace: List[Dict[str, Any]] = []

        # ---------------- LAYER 1: Fast Prefilter ----------------
        r1 = self._run_layer(1, trace, self.layer1.check, text)
        d1 = parse_decision(r1.decision)
        if d1 in (Decision.BLOCK, Decision.REVIEW):
            return self._finalize(d1, 1, r1.reason, trace, start_total)

        # ---------------- LAYER 2: Feature Classifier ----------------
        r2 = self._run_layer(2, trace, self.layer2.check, text, top_similarity=r1.confidence)
        d2 = parse_decision(r2.decision)
        if d2 is not None:  # a final decision; None means ESCALATE to Layer 3
            return self._finalize(d2, 2, r2.reason, trace, start_total)

        # ---------------- LAYER 3: Deep Classifier ----------------
        r3 = self._run_layer(3, trace, self.layer3.check, text)
        d3 = parse_decision(r3.decision)
        if d3 is None:  # unknown or non-final answer at the last layer: fail closed
            d3 = Decision.REVIEW
        return self._finalize(d3, 3, r3.reason, trace, start_total)

    def validate_action(self, action_type: str, payload: Dict[str, Any], user=None) -> Dict[str, Any]:
        """Validates outbound agent action requests via Layer 4."""
        t0 = time.perf_counter()
        res = self.layer4.validate_action(action_type, payload, user=user)
        res["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return res

    def health(self) -> Dict[str, Any]:
        """
        Per-layer readiness. A layer whose model is missing reports `degraded` and the
        engine will route its ALLOW decisions to REVIEW (see `process_input`).
        """
        l1_degraded = bool(getattr(self.layer1, "degraded", False))
        l1_vector = getattr(self.layer1, "index", None) is not None
        l2_ok = getattr(self.layer2, "model", None) is not None
        l3_ok = (
            getattr(self.layer3, "model", None) is not None
            and getattr(self.layer3, "tokenizer", None) is not None
        )
        layers = {
            "layer1": {"status": "degraded" if l1_degraded else "ok", "semantic_index": l1_vector,
                       "error": getattr(self.layer1, "vector_error", None)},
            "layer2": {"status": "ok" if l2_ok else "degraded", "model_loaded": l2_ok},
            "layer3": {"status": "ok" if l3_ok else "degraded", "model_loaded": l3_ok},
            "layer4": {"status": "ok"},
        }
        degraded = [name for name, info in layers.items() if info["status"] == "degraded"]
        return {
            "status": "degraded" if degraded else "healthy",
            "degraded_layers": degraded,
            "layers": layers,
        }

    def _run_layer(
        self,
        layer_no: int,
        trace: List[Dict[str, Any]],
        fn: Callable[..., Dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> LayerResult:
        """Run one layer, time it, normalize its result and append it to the trace."""
        t0 = time.perf_counter()
        try:
            result = LayerResult.from_dict(fn(*args, **kwargs))
        except Exception as exc:  # a crashing layer must not become an implicit ALLOW
            result = LayerResult(
                layer=layer_no,
                decision=Decision.REVIEW.name,
                reason=f"layer{layer_no}_error:{type(exc).__name__}",
                degraded=True,
            )
        result.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        trace.append(result.to_dict())
        return result

    def _finalize(
        self,
        decision: Decision,
        stopped_at_layer: int,
        reason: str,
        trace: List[Dict[str, Any]],
        start_total: float,
    ) -> Dict[str, Any]:
        degraded_layers = [int(step["layer"]) for step in trace if step.get("degraded")]
        if degraded_layers:
            # A degraded layer ran on this request: never let it end in ALLOW.
            floor = Decision.REVIEW if decision == Decision.ALLOW else decision
            if floor != decision:
                reason = f"degraded_fail_closed:layer{degraded_layers[-1]}:{reason}"
            decision = max_decision(decision, floor)
        return self._build_response(decision, stopped_at_layer, reason, trace, start_total, degraded_layers)

    def _build_response(
        self,
        decision: Decision,
        stopped_at_layer: int,
        reason: str,
        trace: List[Dict[str, Any]],
        start_total: float,
        degraded_layers: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        total_ms = round((time.perf_counter() - start_total) * 1000, 2)
        degraded_layers = degraded_layers or []
        return {
            "decision": decision.name,
            "stopped_at_layer": stopped_at_layer,
            "final_reason": reason,
            "total_latency_ms": total_ms,
            "degraded": bool(degraded_layers),
            "degraded_layers": degraded_layers,
            "trace": trace,
        }
