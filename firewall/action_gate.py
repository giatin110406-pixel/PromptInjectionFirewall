"""
Layer 4 gate: decides what happens to an action an agent wants to run.

Order of checks (the first that fires decides):
  1. hard rules      firewall/layer4.py (role, limits, OTP, no self-escalation...). Rejected = BLOCK.
  2. tainted session the session has seen untrusted content that carried an instruction. The policy file says
                     per action whether that means BLOCK, REVIEW or nothing.
  3. human check     actions that are always reviewed, or whose amount reaches `review_over`.
  4. rate limit      too many sensitive actions in the window.
  5. otherwise       ALLOW.

Why the taint check exists: an email that says "refund 2 million to this account" may pass every text filter if
the wording is new. The action it provokes is still unusual for that session, and this layer sees the action,
not the wording.
"""
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

import yaml

from firewall.layer4 import Layer4Validator
from firewall.review_queue import ReviewQueue
from firewall.session import TaintStore

DEFAULT_POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policies.yaml")
SENSITIVE_CLASSES = {"money", "identity", "privilege", "data"}


def load_policy(path: str = DEFAULT_POLICY) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle)
    if not isinstance(policy, dict) or "actions" not in policy:
        raise ValueError(f"{path}: not a valid action policy")
    return policy


class ActionGate:
    def __init__(self, validator: Optional[Layer4Validator] = None, taint: Optional[TaintStore] = None,
                 queue: Optional[ReviewQueue] = None, policy: Optional[Dict[str, Any]] = None,
                 clock=time.time):
        self.validator = validator or Layer4Validator()
        self.taint = taint or TaintStore()
        self.queue = queue or ReviewQueue()
        self.policy = policy or load_policy()
        self._clock = clock
        self._recent: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def evaluate(self, action_type: str, payload: Dict[str, Any], user=None,
                 session_id: Optional[str] = None, skip=()) -> Dict[str, Any]:
        """`skip` (manual testing only): 'L4_HARD' skips the hard rules, 'L4_TAINT' ignores the session taint,
        'L4_POLICY' skips the review thresholds and the rate limit."""
        started = time.perf_counter()
        skip = {str(s).upper() for s in (skip or ())}
        if "L4_HARD" in skip:
            base = {"layer": 4, "decision": "ALLOW", "validated_data": dict(payload or {}), "reason": None}
        else:
            base = self.validator.validate_action(action_type, payload, user=user)
        tainted = self.taint.is_tainted(session_id)
        result: Dict[str, Any] = dict(base)
        result.update(layer=4, tainted=tainted, review_id=None, skipped=sorted(x for x in skip if x.startswith("L4")))

        if base["decision"] != "ALLOW":
            result["decision"] = "BLOCK"
            result["check"] = "hard_rule"
        else:
            decision, reason, check = self._policy_decision(action_type.lower(), payload, tainted and "L4_TAINT" not in skip,
                                                            session_id, skip_policy="L4_POLICY" in skip)
            result.update(decision=decision, reason=reason, check=check)
            if decision == "REVIEW":
                item = self.queue.add(action_type, payload, reason, session_id=session_id,
                                      user_id=getattr(user, "user_id", None) or payload.get("user_id"), tainted=tainted)
                result["review_id"] = item["id"]
                result["validated_data"] = None   # not cleared to run until a reviewer approves
            elif decision == "BLOCK":
                result["validated_data"] = None
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ------------------------------------------------------------------
    def _policy_decision(self, action: str, payload: Dict[str, Any], tainted: bool, session_id: Optional[str],
                         skip_policy: bool = False):
        rule = self.policy["actions"].get(action, {})
        sensitive = rule.get("class") in SENSITIVE_CLASSES

        if tainted:
            reaction = rule.get("when_tainted", "allow")
            if reaction == "block":
                return "BLOCK", f"tainted_session:{action}_after_untrusted_instruction", "taint"
            if reaction == "review":
                return "REVIEW", f"tainted_session:{action}_needs_human_confirmation", "taint"

        if skip_policy:
            return "ALLOW", None, "none"
        if rule.get("always_review"):
            return "REVIEW", f"policy:{action}_always_needs_human_confirmation", "policy"
        over = rule.get("review_over")
        if over:
            try:
                value = float(payload.get(over["field"], 0) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value >= float(over["value"]):
                return "REVIEW", f"policy:{over['field']}_{value:g}_reaches_review_limit_{over['value']}", "policy"

        if sensitive and self._rate_limited(session_id or "anonymous"):
            return "REVIEW", "rate_limit:too_many_sensitive_actions", "rate_limit"
        return "ALLOW", None, "none"

    def _rate_limited(self, key: str) -> bool:
        """Records one sensitive action and tells whether the window is full."""
        window = float(self.policy["rate_limit"]["window_seconds"])
        limit = int(self.policy["rate_limit"]["max_sensitive_actions"])
        now = self._clock()
        with self._lock:
            events = self._recent[key]
            while events and events[0] < now - window:
                events.popleft()
            if len(events) >= limit:
                return True
            events.append(now)
            return False
