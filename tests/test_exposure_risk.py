"""Risk matrix of Layer 4 (WP4): a doubtful chunk keeps the question even when the user chose the destination, and the
Layer 2 score can only make a decision stricter."""
import itertools

import pytest

from firewall.action_gate import ActionGate, load_policy
from firewall.review_queue import ReviewQueue
from firewall.session import TaintStore

RANK = {"ALLOW": 0, "REVIEW": 1, "BLOCK": 2}


@pytest.fixture
def gate(tmp_path):
    return ActionGate(taint=TaintStore(), queue=ReviewQueue(str(tmp_path / "q.json")), policy=load_policy())


def transfer(to="0451000999888"):
    return {"user_id": "u1", "user_role": "user", "from_account": "111222", "to_account": to, "bank_code": "VCB",
            "amount": 1_000_000, "otp_verified": True}


def test_policy_value_is_loaded(gate):
    assert gate.risk_low == pytest.approx(0.30)


def test_session_risk_is_the_highest_chunk_score():
    taint = TaintStore()
    taint.expose("s", "email", "a", "ALLOW", risk=0.02)
    taint.expose("s", "web", "b", "SANITIZE", risk=0.41)
    taint.expose("s", "rag", "c", "ALLOW")
    assert taint.exposure_risk("s") == pytest.approx(0.41) and taint.exposure_risk("other") == 0.0
    taint.mark("s", "web", "layer2_attack_score:0.99", "d")
    assert taint.exposure_risk("s") == 1.0


def test_user_typed_destination_with_a_quiet_read_runs(gate):
    gate.values.add_trusted("q", "chuyển 1 triệu vào 0451000999888")
    gate.taint.expose("q", "email", "m1", "ALLOW", risk=0.03)
    assert gate.evaluate("transfer_money", transfer(), session_id="q")["decision"] == "ALLOW"


def test_user_typed_destination_with_a_doubtful_read_is_asked_about(gate):
    gate.values.add_trusted("d", "chuyển 1 triệu vào 0451000999888")
    gate.taint.expose("d", "email", "m1", "SANITIZE", risk=0.52)
    out = gate.evaluate("transfer_money", transfer(), session_id="d")
    assert out["decision"] == "REVIEW" and out["check"] == "exposure_risk" and out["review_by"] == "user"
    assert "content_risk_0.52" in out["reason"]


def test_detection_mode_ignores_the_risk(gate):
    gate.exposure_mode = "detection"
    gate.values.add_trusted("m", "chuyển vào 0451000999888")
    gate.taint.expose("m", "email", "m1", "SANITIZE", risk=0.6)
    assert gate.evaluate("transfer_money", transfer(), session_id="m")["decision"] == "ALLOW"


@pytest.mark.parametrize("origin, risk, mode", itertools.product(
    ["typed", "saved", "content", "nowhere"], [0.0, 0.1, 0.29, 0.3, 0.5, 0.64], ["provenance", "detection"]))
def test_the_score_never_relaxes_a_decision(tmp_path, origin, risk, mode):
    """Same session, same action, with and without the chunk score: the decision with the score is never weaker."""
    decisions = []
    for with_score in (False, True):
        g = ActionGate(taint=TaintStore(), queue=ReviewQueue(str(tmp_path / f"q{with_score}.json")), policy=load_policy())
        g.exposure_mode = mode
        to = {"typed": "0451000999888", "saved": "0451000123456", "content": "0451000777666", "nowhere": "0451000555444"}[origin]
        if origin == "typed":
            g.values.add_trusted("s", f"chuyển vào {to}")
        if origin == "content":
            g.values.add_untrusted("s", f"STK: {to}", "email", "m1")
        g.taint.expose("s", "email", "m1", "ALLOW", risk=risk if with_score else None)
        decisions.append(g.evaluate("transfer_money", transfer(to), session_id="s")["decision"])
    without, with_ = decisions
    assert RANK[with_] >= RANK[without]
    if origin in ("content", "nowhere") and mode == "provenance":
        assert without == with_ == "REVIEW"           # an untrusted destination is asked about at any score
