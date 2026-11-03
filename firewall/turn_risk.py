"""
Session risk across chat turns (WP6 of docs/implementation_plan_v4_vi.md). Rule-based, no trained model.

Layer 1 and Layer 2 judge one message at a time. A user who pushes the assistant step by step ("only this once",
"pretend the rule is off", "now do it for real") can keep every single message under the Layer 2 threshold. This module
keeps, per session, the Layer 2 score of each user turn and two signals:

  turn_risk    weighted mean of the last `window` scores, the newest weighing most (weight `decay` ** age). A turn
               held or blocked by Layer 1 before Layer 2 ran counts as 1.0.
  borderline   number of consecutive latest turns whose score lies in the uncertain band [low, high): Layer 2 let
               them through, but only just.

Rule (initial values, chosen by hand, not tuned on any test set):
  turn_risk >= 0.7, or 3 or more borderline turns in a row  ->  the current message is held (REVIEW), and the session
  becomes EXPOSED, so a sensitive action after it needs a confirmation like after reading untrusted content.

A model would need labelled multi-turn conversations; none are available yet, so the first version is these rules.
With a StateStore (FIREWALL_STATE_DB) the turns survive a restart like the other session state.
"""
import threading
import time
from typing import Any, Dict, List, Optional

from firewall.state_store import StateStore

NAMESPACE = "turns"
DEFAULT_TTL_SECONDS = 30 * 60


class TurnRisk:
    def __init__(self, low: float = 0.45, high: float = 0.65, risk_review: float = 0.7, borderline_review: int = 3,
                 window: int = 5, decay: float = 0.7, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=time.time,
                 store: Optional[StateStore] = None):
        self.low, self.high = low, high
        self.risk_review, self.borderline_review = risk_review, borderline_review
        self.window, self.decay = window, decay
        self.ttl = ttl_seconds
        self._clock = clock
        self._store = store
        self._lock = threading.Lock()
        self._turns: Dict[str, Dict[str, Any]] = {}

    def _load(self, session_id: str) -> Dict[str, Any]:
        cutoff = self._clock() - self.ttl
        for key in [k for k, v in self._turns.items() if v["last_seen"] < cutoff]:
            del self._turns[key]
        if self._store is not None:
            self._store.delete_older(NAMESPACE, cutoff)
            row = self._store.get(NAMESPACE, session_id)
            if row is not None:
                self._turns[session_id] = row
        return self._turns.setdefault(session_id, {"scores": [], "count": 0, "last_seen": self._clock()})

    def _assess(self, scores: List[float]) -> Dict[str, Any]:
        recent = scores[-self.window:]
        weights = [self.decay ** age for age in range(len(recent) - 1, -1, -1)]
        risk = sum(w * s for w, s in zip(weights, recent)) / sum(weights) if recent else 0.0
        streak = 0
        for score in reversed(scores):
            if not self.low <= score < self.high:
                break
            streak += 1
        reasons = []
        if risk >= self.risk_review:
            reasons.append(f"turn_risk:{risk:.2f}")
        if streak >= self.borderline_review:
            reasons.append(f"borderline_turns:{streak}")
        return {"turn_risk": round(risk, 4), "borderline_streak": streak, "turns": len(scores),
                "review": bool(reasons), "reason": "+".join(reasons) or None}

    def record(self, session_id: str, score: float) -> Dict[str, Any]:
        """Add one user turn and return the assessment of the session after it."""
        with self._lock:
            state = self._load(session_id)
            state["scores"] = (state["scores"] + [round(float(score), 4)])[-max(self.window, self.borderline_review * 2):]
            state["count"] += 1
            state["last_seen"] = self._clock()
            if self._store is not None:
                self._store.put(NAMESPACE, session_id, state, state["last_seen"])
            return dict(self._assess(state["scores"]), turns=state["count"])

    def info(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            state = self._load(session_id)
            return dict(self._assess(state["scores"]), turns=state["count"], scores=list(state["scores"]))

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._turns.clear()
            else:
                self._turns.pop(session_id, None)
            if self._store is not None:
                self._store.delete(NAMESPACE, session_id)


def layer2_score(result: Dict[str, Any]) -> float:
    """The attack score of one process_input result: Layer 2's top window score; 1.0 when Layer 1 stopped the message
    first; 0.0 when no layer scored it (Layer 2 switched off)."""
    if result.get("plain_read_request") or result.get("plain_greeting"):
        return 0.0  # bounded user intent; the uncorrected model score remains visible in the trace
    adjudication = result.get("judge_adjudication") or {}
    if (result.get("decision") == "ALLOW" and not result.get("degraded")
            and adjudication.get("source") == "user" and adjudication.get("verdict") == "benign"
            and adjudication.get("full_text_reviewed")):
        # A false-positive L2 score must not immediately re-block the same user
        # through session risk. Existing history and taint are never cleared.
        return max(0.0, min(1.0, 1.0 - float(adjudication["confidence"])))
    for step in result.get("trace", []):
        if step.get("layer") == 2 and step.get("decision") != "SKIPPED":
            details = step.get("details") if isinstance(step.get("details"), dict) else {}
            if "max_window_score" in details:
                return float(details["max_window_score"])
            confidence = float(step.get("confidence") or 0.0)
            return 1.0 - confidence if step.get("decision") == "ALLOW" else confidence
    if result.get("stopped_at_layer") == 1 and result.get("decision") in ("BLOCK", "REVIEW"):
        return 1.0
    return 0.0
