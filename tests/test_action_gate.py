"""Layer 4 gate: hard rules, taint reaction, human-review thresholds, rate limit, review queue."""
import pytest

from firewall.action_gate import ActionGate, load_policy
from firewall.review_queue import ReviewQueue
from firewall.session import TaintStore


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def gate(tmp_path):
    clock = _Clock()
    g = ActionGate(taint=TaintStore(clock=clock), queue=ReviewQueue(str(tmp_path / "q.json")),
                   policy=load_policy(), clock=clock)
    g.clock = clock
    return g


def refund(amount=50.0):
    return {"user_id": "u1", "order_id": "o1", "amount": amount, "order_value": 500.0, "user_role": "finance_lead"}


def transfer(amount=1_000_000, **extra):
    return {"user_id": "u1", "user_role": "user", "from_account": "111222", "to_account": "999888",
            "bank_code": "VCB", "amount": amount, "otp_verified": True, **extra}


def test_small_refund_is_allowed(gate):
    out = gate.evaluate("refund", refund(50.0), session_id="s1")
    assert out["decision"] == "ALLOW" and out["review_id"] is None and out["validated_data"]


def test_hard_rule_violation_is_blocked_and_not_reviewable(gate):
    out = gate.evaluate("refund", refund(900.0), session_id="s1")      # above 110% of the order value
    assert out["decision"] == "BLOCK" and out["check"] == "hard_rule"
    assert gate.queue.list() == []


def test_large_but_legitimate_refund_waits_for_a_human(gate):
    out = gate.evaluate("refund", refund(150.0), session_id="s1")
    assert out["decision"] == "REVIEW" and out["check"] == "policy" and out["validated_data"] is None
    pending = gate.queue.list("pending")
    assert len(pending) == 1 and pending[0]["id"] == out["review_id"] and pending[0]["action_type"] == "refund"


def test_tainted_session_blocks_money_transfer_even_when_it_is_small(gate):
    assert gate.evaluate("transfer_money", transfer(), session_id="s2")["decision"] == "ALLOW"
    gate.taint.mark("s2", "email", "layer2_attack_score:0.99", "mail1")
    out = gate.evaluate("transfer_money", transfer(), session_id="s2")
    assert out["decision"] == "BLOCK" and out["check"] == "taint" and out["tainted"] is True


def test_tainted_session_sends_a_small_refund_to_review(gate):
    gate.taint.mark("s3", "web", "x")
    out = gate.evaluate("refund", refund(20.0), session_id="s3")
    assert out["decision"] == "REVIEW" and out["check"] == "taint"


def test_other_sessions_are_not_affected_by_taint(gate):
    gate.taint.mark("poisoned", "email", "x")
    assert gate.evaluate("transfer_money", transfer(), session_id="clean")["decision"] == "ALLOW"


def test_taint_expires(gate):
    gate.taint.mark("s4", "email", "x")
    gate.clock.now += 31 * 60
    assert gate.evaluate("transfer_money", transfer(), session_id="s4")["decision"] == "ALLOW"


def test_privilege_changes_always_need_a_human(gate):
    payload = {"operator_id": "ops1", "operator_role": "super_admin", "target_user_id": "u9",
               "requested_role": "support_agent", "justification": "New hire on the support team", "ticket_id": "T-1001"}
    out = gate.evaluate("role_escalation", payload, session_id="s5")
    assert out["decision"] == "REVIEW" and "always_needs_human" in out["reason"]


def test_rate_limit_moves_the_sixth_sensitive_action_to_review(gate):
    decisions = [gate.evaluate("transfer_money", transfer(1_000_000 + i), session_id="s6")["decision"] for i in range(6)]
    assert decisions == ["ALLOW"] * 5 + ["REVIEW"]
    gate.clock.now += 61
    assert gate.evaluate("transfer_money", transfer(2_000_000), session_id="s6")["decision"] == "ALLOW"


def test_review_queue_decision_flow(gate):
    out = gate.evaluate("refund", refund(150.0), session_id="s7", user=None)
    item_id = out["review_id"]
    approved = gate.queue.decide(item_id, True, reviewer="finance_lead", note="verified with customer")
    assert approved["status"] == "approved" and approved["reviewer"] == "finance_lead"
    assert gate.queue.decide(item_id, False, reviewer="x") is None          # already decided
    assert gate.queue.list("pending") == [] and len(gate.queue.list("approved")) == 1


def test_unknown_action_is_blocked(gate):
    assert gate.evaluate("delete_everything", {}, session_id="s8")["decision"] == "BLOCK"


def test_policy_file_names_only_known_actions():
    from firewall.layer4 import Layer4Validator
    assert set(load_policy()["actions"]) <= set(Layer4Validator.ACTION_MODELS)
