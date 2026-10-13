"""
Firewall Orchestrator: Multi-Layer Threat Detection Pipeline.
Coordinates Layer 1 (Prefilter), Layer 2 (multilingual classifier), Layer 3 (optional
judge) and Layer 4 (Policy Validator), producing a transparent trace.

Contract (see firewall/types.py):
- Final decisions are ALLOW / SANITIZE / REVIEW / BLOCK. When layers disagree the
  most severe one wins.
- Fail closed: a layer that ran without a valid model (`degraded=true`) or that
  raised an error can never produce a final ALLOW. The request becomes REVIEW.
"""
import time
from typing import Any, Callable, Dict, List, Optional

from firewall.classifier import MultilingualClassifier
from firewall.layer1 import Layer1Prefilter
from firewall.action_gate import ActionGate
from firewall.layer4 import Layer4Validator
from firewall.output_guard import OutputGuard
from firewall.review_queue import ReviewQueue
from firewall.session import TaintStore
from firewall.spotlight import Chunk, ContextScanner
from firewall.types import Decision, LayerResult, max_decision, parse_decision


# A Layer 2 block below this score, with no agreement from Layer 1 and no judge, is held for review instead of blocked
# (PrepareForBCTĐ2/04_layer2_classifier.md: of Layer 2's lone blocks scoring 0.67-0.98, 32% were safe texts; when Layer 1
# agrees, 98.7% of blocks are right).
DEFAULT_SOFT_BLOCK_BELOW = 0.98

# Layer 2 score edges handed to the judge (chosen on the validation and dev sets; see PrepareForBCTĐ2/10_layer3_judge.md)
DEFAULT_ESCALATE_LOW = 0.30
DEFAULT_ESCALATE_HIGH = 0.98


def normalize_skip(skip) -> set:
    """Layer names to switch off for one call: 'L1', 'L2', 'L3', 'clean', 'L4_hard', 'L4_taint', 'L4_policy', 'L5'
    (ints 1..5 are read as L1..L5). For manual testing only; the API allows it to a security admin in demo mode."""
    out = set()
    for item in skip or ():
        text = f"L{item}" if isinstance(item, int) else str(item).strip()
        out.add(text.upper())
    return out


def _skipped_step(layer: int, note: str = "tắt thủ công để thử layer khác") -> Dict[str, Any]:
    return {"layer": layer, "decision": "SKIPPED", "confidence": 0.0, "reason": note, "latency_ms": 0.0, "degraded": False}


class FirewallOrchestrator:
    def __init__(
        self,
        layer1: Optional[Layer1Prefilter] = None,
        layer2: Optional[Any] = None,
        layer3: Optional[Any] = None,
        layer4: Optional[Layer4Validator] = None,
        soft_block_below: Any = "auto",
    ):
        self.layer1 = layer1 or Layer1Prefilter()
        self.layer2 = layer2 or MultilingualClassifier()
        # "auto": the real classifier gets the consensus policy, test stubs keep their plain behaviour. None switches it off.
        self.soft_block_below = (DEFAULT_SOFT_BLOCK_BELOW if isinstance(self.layer2, MultilingualClassifier) else None) \
            if soft_block_below == "auto" else soft_block_below
        # Layer 3 (an LLM judge) is optional. Without one Layer 2 decides alone; with one, Layer 2's uncertain
        # scores (both edges, see firewall/classifier.py) go to the judge.
        self.layer3 = layer3
        if hasattr(layer3, "resolve") and hasattr(self.layer2, "escalate_low"):
            if self.layer2.escalate_low is None:
                self.layer2.escalate_low = DEFAULT_ESCALATE_LOW
            if self.layer2.escalate_high is None:
                self.layer2.escalate_high = DEFAULT_ESCALATE_HIGH
        self.layer4 = layer4 or Layer4Validator()
        self.taint = TaintStore()
        self.output_guard = OutputGuard()
        self.review_queue = ReviewQueue()
        self.actions = ActionGate(validator=self.layer4, taint=self.taint, queue=self.review_queue)

    def process_input(self, text: str, source: str = "user", skip=(), use_judge: bool = True) -> Dict[str, Any]:
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
        skip = normalize_skip(skip)
        judge_wanted = use_judge and "L3" not in skip

        # ---------------- LAYER 1: Fast Prefilter ----------------
        if "L1" in skip:
            trace.append(_skipped_step(1))
            r1 = LayerResult(layer=1, decision="PASS")
        else:
            r1 = self._run_layer(1, trace, self.layer1.check, text)
            d1 = parse_decision(r1.decision)
            if d1 in (Decision.BLOCK, Decision.REVIEW):
                return self._finalize(d1, 1, r1.reason, trace, start_total)

        # ---------------- LAYER 2: Feature Classifier ----------------
        if "L2" in skip:
            trace.append(_skipped_step(2))
            if judge_wanted and hasattr(self.layer3, "resolve"):     # test the judge on its own: ask it about the raw text
                r3 = self._run_layer(3, trace, self.layer3.check, text, side="allow", source=source, l2_score=None)
                return self._finalize(parse_decision(r3.decision) or Decision.REVIEW, 3, r3.reason, trace, start_total)
            return self._finalize(Decision.ALLOW, 2, "layer2_skipped" + (":layer1_skipped" if "L1" in skip else ""), trace, start_total)
        r2 = self._run_layer(2, trace, self.layer2.check, text, top_similarity=r1.confidence)
        d2 = parse_decision(r2.decision)
        if d2 == Decision.BLOCK and self._unconfirmed_block(r2):
            # Layer 2 alone, not sure enough: hold the request instead of blocking it (Layer 1 did not agree).
            return self._finalize(Decision.REVIEW, 2, f"layer2_unconfirmed:{r2.reason}", trace, start_total)
        if d2 is not None:  # a final decision; None means ESCALATE to Layer 3
            return self._finalize(d2, 2, r2.reason, trace, start_total)

        # ---------------- LAYER 3: judge for borderline cases (optional) ----------------
        if self.layer3 is None:
            return self._finalize(Decision.REVIEW, 2, "layer3_not_configured:" + r2.reason, trace, start_total)
        if hasattr(self.layer3, "resolve") and not judge_wanted:
            # The judge was not requested for this call (it can cost money): Layer 2 decides alone, as it does without a judge.
            side = (r2.details.get("details", {}) if isinstance(r2.details, dict) else {}).get("side", "allow")
            if "L3" in skip:
                trace.append(_skipped_step(3))
            label = "attack" if side == "block" else "borderline"
            held = Decision.REVIEW if side == "block" else Decision.ALLOW      # a lone, unsure block is held, never hard
            return self._finalize(held, 2, f"layer2_{label}_no_judge:{r2.reason}", trace, start_total)
        if hasattr(self.layer3, "resolve"):          # the LLM judge: read the window Layer 2 was unsure about
            l2_details = r2.details.get("details", {}) if isinstance(r2.details, dict) else {}
            r3 = self._run_layer(3, trace, self.layer3.check, l2_details.get("top_window_text") or text,
                                 side=l2_details.get("side", "allow"), source=source, l2_score=r2.confidence)
        else:                                         # legacy classifier objects keep their old call
            r3 = self._run_layer(3, trace, self.layer3.check, text)
        d3 = parse_decision(r3.decision)
        if d3 is None:  # unknown or non-final answer at the last layer: fail closed
            d3 = Decision.REVIEW
        return self._finalize(d3, 3, r3.reason, trace, start_total)

    def _unconfirmed_block(self, r2) -> bool:
        return self.soft_block_below is not None and float(r2.confidence or 0.0) < self.soft_block_below

    def process_context(self, chunks: List[Dict[str, Any]], session_id: Optional[str] = None, skip=(),
                        use_judge: bool = True) -> Dict[str, Any]:
        """
        Scan untrusted content (RAG passages, emails, web pages, tool output) before it reaches the model.
        `chunks`: dicts with `id`, `text` and optionally `source`. Returns the decision, a verdict per chunk,
        and `sanitized_context`: the surviving text, delimited and datamarked (see firewall/spotlight.py).
        A chunk that carried an instruction taints the session; Layer 4 reads that flag.
        """
        parsed = [Chunk(id=str(c.get("id", i)), text=str(c.get("text", "")), source=str(c.get("source", "document")))
                  for i, c in enumerate(chunks)]
        skip = normalize_skip(skip)
        scanner = ContextScanner(lambda t: self.process_input(t, source="untrusted", skip=skip, use_judge=use_judge))
        result = scanner.scan(parsed, clean="CLEAN" not in skip).to_dict()
        result["skipped"] = sorted(skip)
        if session_id:
            for entry in result["chunks"]:
                if entry["suspicious"]:
                    self.taint.mark(session_id, entry["source"], entry["reason"], entry["id"])
        result["session_tainted"] = self.taint.is_tainted(session_id)
        return result

    def check_output(self, text: str, session_id: Optional[str] = None, allow_text: str = "",
                     protected_texts=(), skip=()) -> Dict[str, Any]:
        """
        Layer 5: inspect what the agent is about to say. `allow_text` is what the user wrote (its own data may be
        repeated back); `protected_texts` are texts that must not be echoed (the system prompt).
        Returns decision ALLOW / SANITIZE / BLOCK and `sanitized_text` (empty when BLOCK).
        """
        if "L5" in normalize_skip(skip):
            return {"layer": 5, "decision": "ALLOW", "degraded": False, "confidence": 0.0, "reason": "layer5_skipped",
                    "sanitized_text": text, "findings": [], "latency_ms": 0.0, "skipped": True}
        return self.output_guard.check(text, session_id=session_id, allow_text=allow_text, protected_texts=protected_texts)

    def validate_action(self, action_type: str, payload: Dict[str, Any], user=None,
                        session_id: Optional[str] = None, skip=()) -> Dict[str, Any]:
        """
        Layer 4: decide what happens to an action an agent wants to run (ALLOW, REVIEW or BLOCK).
        `session_id` links the action to the context scans of the same session (taint, rate limit).
        """
        return self.actions.evaluate(action_type, payload, user=user, session_id=session_id, skip=normalize_skip(skip))

    def health(self) -> Dict[str, Any]:
        """
        Per-layer readiness. A layer whose model is missing reports `degraded` and the
        engine will route its ALLOW decisions to REVIEW (see `process_input`).
        """
        l1_degraded = bool(getattr(self.layer1, "degraded", False))
        l1_vector = getattr(self.layer1, "index", None) is not None
        l2_ok = getattr(self.layer2, "model", None) is not None
        l3_configured = self.layer3 is not None
        l3_ok = l3_configured and (
            getattr(self.layer3, "model", None) is not None
            and getattr(self.layer3, "tokenizer", None) is not None
        )
        layers = {
            "layer1": {"status": "degraded" if l1_degraded else "ok", "semantic_index": l1_vector,
                       "error": getattr(self.layer1, "vector_error", None)},
            "layer2": {"status": "ok" if l2_ok else "degraded", "model_loaded": l2_ok,
                       "error": getattr(self.layer2, "error", None)},
            "layer3": self._layer3_health(l3_configured, l3_ok),
            "layer4": {"status": "ok"},
            "layer5": {"status": "ok"},
        }
        degraded = [name for name, info in layers.items() if info["status"] == "degraded"]
        return {
            "status": "degraded" if degraded else "healthy",
            "degraded_layers": degraded,
            "layers": layers,
        }

    def _layer3_health(self, configured: bool, model_ok: bool) -> Dict[str, Any]:
        if not configured:
            return {"status": "disabled", "model_loaded": False}
        if hasattr(self.layer3, "resolve"):           # LLM judge: ok when a provider is set
            provider = getattr(self.layer3, "provider", None)
            return {"status": "ok" if provider is not None else "disabled", "provider": getattr(provider, "name", None),
                    "calls_today": getattr(getattr(self.layer3, "budget", None), "used", None)}
        return {"status": "ok" if model_ok else "degraded", "model_loaded": model_ok}

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
