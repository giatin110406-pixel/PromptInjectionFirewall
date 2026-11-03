"""
Layer 4 gate: decides what happens to an action an agent wants to run.

Order of checks (the first that fires decides):
  1. hard rules      firewall/layer4.py (role, limits, OTP, no self-escalation...). Rejected = BLOCK.
  2. tainted session the session has seen untrusted content that carried an instruction. The policy file says
                     per action whether that means BLOCK, REVIEW or nothing (`when_tainted`).
  3. exposed session the session has read untrusted content, flagged or not (exposure mode "provenance" only).
                     `when_exposed` says BLOCK, REVIEW or nothing; sensitive actions default to REVIEW. A REVIEW is
                     lifted when every `provenance_fields` value (destination account, order...) was typed by the
                     user or is in their saved recipients (firewall/values.py): then the user chose it, not the content.
                     It is kept when a chunk the session read scored `exposure.risk_low` or more on Layer 2
                     (exposure_risk, WP4): detection only ever adds a question here, it never removes one.
  4. human check     actions that are always reviewed, or whose amount reaches `review_over`.
  5. rate limit      too many sensitive actions in the window.
  6. otherwise       ALLOW.
Actions that send data out (class `communicate`: email, HTTP call, chat message, file share) get one more check right
after the hard rules: a secret in what is sent, to a destination outside the egress allow-list, is a BLOCK; personal
data sent to an untrusted destination in an exposed session is a BLOCK (firewall/egress.py).

Why the exposure check exists: an email that says "refund 2 million to this account" may pass every text filter if
the wording is new, and then the session is never tainted. Measured on InjecAgent with the v3 engine, 14 of 17
money transfers asked for by a poisoned tool response went through for that reason. This layer sees where the
content came from, not only whether a classifier recognised it, so a missed attack still meets a confirmation.
"""
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional

import yaml

from firewall.egress import EGRESS_CLASS, EgressGuard, flatten
from firewall.layer4 import Layer4Validator
from firewall.review_queue import ReviewQueue
from firewall.session import EXPOSED, TAINTED, TaintStore
from firewall.values import TRUSTED, TrustedBook, ValueLedger, load_trusted_book, normalize_value

DEFAULT_POLICY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policies.yaml")
SENSITIVE_CLASSES = {"money", "identity", "privilege", "data", EGRESS_CLASS}
EXPOSURE_MODES = ("provenance", "detection")
REACTIONS = ("block", "review", "allow")


def load_policy(path: str = DEFAULT_POLICY) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle)
    if not isinstance(policy, dict) or "actions" not in policy:
        raise ValueError(f"{path}: not a valid action policy")
    mode = (policy.get("exposure") or {}).get("mode", "provenance")
    if mode not in EXPOSURE_MODES:
        raise ValueError(f"{path}: exposure.mode must be one of {EXPOSURE_MODES}, not {mode!r}")
    for name, rule in policy["actions"].items():
        for key in ("when_tainted", "when_exposed"):
            if key in rule and rule[key] not in REACTIONS:
                raise ValueError(f"{path}: {name}.{key} must be one of {REACTIONS}, not {rule[key]!r}")
        for key in ("provenance_fields", "content_fields"):
            fields = rule.get(key, [])
            if not isinstance(fields, list) or not all(isinstance(f, str) and f for f in fields):
                raise ValueError(f"{path}: {name}.{key} must be a list of payload keys")
    allowlist = (policy.get("egress") or {}).get("allowlist", [])
    if not isinstance(allowlist, list):
        raise ValueError(f"{path}: egress.allowlist must be a list")
    return policy


class ActionGate:
    def __init__(self, validator: Optional[Layer4Validator] = None, taint: Optional[TaintStore] = None,
                 queue: Optional[ReviewQueue] = None, policy: Optional[Dict[str, Any]] = None,
                 clock=time.time, values: Optional[ValueLedger] = None, trusted_book: Optional[TrustedBook] = None,
                 egress: Optional[EgressGuard] = None):
        self.validator = validator or Layer4Validator()
        self.taint = taint or TaintStore()
        self.queue = queue or ReviewQueue()
        self.policy = policy or load_policy()
        self.values = values or ValueLedger(clock=clock)
        self.trusted_book = trusted_book if trusted_book is not None else load_trusted_book()
        self.egress = egress or EgressGuard((self.policy.get("egress") or {}).get("allowlist", []))
        # "provenance" or "detection" (see policies.yaml). An attribute so an evaluation can compare both on one engine.
        self.exposure_mode = (self.policy.get("exposure") or {}).get("mode", "provenance")
        # WP4: an exposed session whose destinations the user chose is still asked about when a chunk it read scored this
        # high on Layer 2 (below the threshold, so not tainted). policies.yaml exposure.risk_low; 1.0 switches it off.
        self.risk_low = float((self.policy.get("exposure") or {}).get("risk_low", 1.0))
        self._clock = clock
        self._recent: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def evaluate(self, action_type: str, payload: Dict[str, Any], user=None,
                 session_id: Optional[str] = None, skip=(), exposure_mode: Optional[str] = None) -> Dict[str, Any]:
        """`skip` (manual testing only): 'L4_HARD' skips the hard rules, 'L4_TAINT' ignores the session state (taint
        and exposure), 'L4_POLICY' skips the review thresholds and the rate limit."""
        started = time.perf_counter()
        mode = self.exposure_mode if exposure_mode is None else exposure_mode
        if mode not in EXPOSURE_MODES:
            raise ValueError(f"exposure_mode must be one of {EXPOSURE_MODES}")
        skip = {str(s).upper() for s in (skip or ())}
        if "L4_HARD" in skip:
            base = {"layer": 4, "decision": "ALLOW", "validated_data": dict(payload or {}), "reason": None}
        else:
            base = self.validator.validate_action(action_type, payload, user=user)
        level = self.taint.level(session_id)
        tainted, exposed = level == TAINTED, level in (EXPOSED, TAINTED)
        provenance = self.taint.exposure_sources(session_id) if exposed else []
        user_id = getattr(user, "user_id", None) or (payload or {}).get("user_id")
        values = self.value_provenance(action_type.lower(), payload or {}, session_id, user_id) if exposed else []
        result: Dict[str, Any] = dict(base)
        result.update(layer=4, tainted=tainted, exposed=exposed, session_level=level, provenance=provenance,
                      value_provenance=values, exposure_mode=mode, review_id=None, review_by=None,
                      skipped=sorted(x for x in skip if x.startswith("L4")))

        rule = self.policy["actions"].get(action_type.lower(), {})
        egress = None
        if rule.get("class") == EGRESS_CLASS and base["decision"] == "ALLOW":
            egress = self._egress_findings(rule, payload or {})
            result["egress"] = egress
        if base["decision"] != "ALLOW":
            result["decision"] = "BLOCK"
            result["check"] = "hard_rule"
        else:
            use_state = "L4_TAINT" not in skip
            stop = None
            if egress is not None and "L4_POLICY" not in skip:
                # the personal-data rule is part of the exposure check: provenance mode only, like `when_exposed`
                exposure_counts = exposed and use_state and mode == "provenance"
                stop = self._egress_decision(action_type.lower(), egress, exposure_counts, values)
            if stop is not None:
                decision, reason, check = stop
            else:
                decision, reason, check = self._policy_decision(action_type.lower(), payload, tainted and use_state,
                                                                session_id, skip_policy="L4_POLICY" in skip,
                                                                exposed=exposed and use_state, values=values,
                                                                exposure_mode=mode)
            result.update(decision=decision, reason=reason, check=check)
            if decision == "REVIEW":
                review_by = self.policy["actions"].get(action_type.lower(), {}).get("review_by", "staff")
                item = self.queue.add(action_type, payload, reason, session_id=session_id, user_id=user_id,
                                      tainted=tainted, exposed=exposed, provenance=provenance, review_by=review_by,
                                      value_provenance=values)
                result["review_id"] = item["id"]
                result["review_by"] = review_by
                result["validated_data"] = None   # not cleared to run until a reviewer approves
            elif decision == "BLOCK":
                result["validated_data"] = None
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    # ------------------------------------------------------------------
    def value_provenance(self, action: str, payload: Dict[str, Any], session_id: Optional[str],
                         user_id: Optional[str]) -> List[Dict[str, Any]]:
        """Where each `provenance_fields` value of the action comes from. The amount is added for the reviewer
        (`decides: False`): it never clears an action on its own."""
        rule = self.policy["actions"].get(action, {})
        out = []
        for field in rule.get("provenance_fields", []):
            values = flatten(payload.get(field)) or [None]     # a missing value stays in the list: unknown origin
            if rule.get("class") == EGRESS_CLASS:
                values = [v for v in values if v is not None]  # optional recipients (cc) may be empty
            for value in values:
                if rule.get("class") == EGRESS_CLASS and self.egress.allowlisted(value):
                    origin = {"origin": TRUSTED, "seen_in": [{"source": "egress_allowlist"}]}
                else:
                    origin = self.values.classify(session_id, value, user_id=user_id, book=self.trusted_book)
                out.append(dict(origin, field=field, value=value, decides=True))
        if rule.get("provenance_fields") and payload.get("amount") is not None:
            out.append(dict(self.values.classify_amount(session_id, payload["amount"]),
                            field="amount", value=payload["amount"], decides=False))
        return out

    def _egress_findings(self, rule: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        """What an egress action sends and where: secrets and personal data found in the content, destinations
        outside the allow-list (saved recipients count as inside: the user registered them beforehand)."""
        found = self.egress.findings(self.egress.content(rule, payload))
        user_id = payload.get("user_id")
        outside = [str(v) for _, v in self.egress.destinations(rule, payload)
                   if not self.egress.allowlisted(v) and not self._in_book(user_id, v)]
        return dict(found, outside_allowlist=outside)

    def _in_book(self, user_id: Optional[str], value: Any) -> bool:
        key = normalize_value(value)
        return bool(key) and self.trusted_book.contains(user_id, key)

    @staticmethod
    def _egress_decision(action: str, egress: Dict[str, Any], exposed: bool, values: List[Dict[str, Any]]):
        if egress["secret"] and egress["outside_allowlist"]:
            return ("BLOCK", f"egress:{action}_sends_{egress['secret'][0]}_to_{egress['outside_allowlist'][0]}",
                    "egress")
        doubtful = [v for v in values if v["decides"] and v["origin"] != TRUSTED]
        if egress["pii"] and exposed and doubtful:
            return ("BLOCK", f"egress:{action}_sends_personal_data_{egress['pii'][0]}_to_untrusted_"
                             f"{doubtful[0]['field']}_after_untrusted_content", "egress")
        return None

    def _policy_decision(self, action: str, payload: Dict[str, Any], tainted: bool, session_id: Optional[str],
                         skip_policy: bool = False, exposed: bool = False, values: Optional[List[Dict[str, Any]]] = None,
                         exposure_mode: Optional[str] = None):
        rule = self.policy["actions"].get(action, {})
        sensitive = rule.get("class") in SENSITIVE_CLASSES

        if tainted:
            reaction = rule.get("when_tainted", "allow")
            if reaction == "block":
                return "BLOCK", f"tainted_session:{action}_after_untrusted_instruction", "taint"
            if reaction == "review":
                return "REVIEW", f"tainted_session:{action}_needs_human_confirmation", "taint"

        if exposed and (self.exposure_mode if exposure_mode is None else exposure_mode) == "provenance":
            # No layer has to recognise the attack: reading untrusted content is enough to ask before a sensitive action.
            reaction = rule.get("when_exposed", "review" if sensitive else "allow")
            if reaction == "block":
                return "BLOCK", f"exposed_session:{action}_after_untrusted_content", "exposure"
            deciding = [v for v in (values or []) if v["decides"]]
            if reaction == "review" and not deciding:
                return "REVIEW", f"exposed_session:{action}_after_untrusted_content_needs_confirmation", "exposure"
            if reaction == "review":
                doubtful = [v for v in deciding if v["origin"] != TRUSTED]
                if doubtful:
                    first = doubtful[0]
                    if first["seen_in"]:
                        where = first["seen_in"][0]
                        return "REVIEW", (f"exposed_session:{action}.{first['field']}_comes_from_untrusted_"
                                          f"{where['source']}:{where.get('chunk_id')}"), "exposure"
                    return "REVIEW", f"exposed_session:{action}.{first['field']}_has_unknown_origin", "exposure"
                # every destination was chosen by the user: no question for the exposure, unless something the session
                # read scored in the uncertain band of Layer 2 (WP4). The score can only add a question, never remove one.
                risk = self.taint.exposure_risk(session_id)
                if risk >= self.risk_low:
                    return ("REVIEW", f"exposed_session:{action}_content_risk_{risk:.2f}_reaches_{self.risk_low:g}",
                            "exposure_risk")

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
