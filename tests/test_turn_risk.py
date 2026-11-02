"""Session risk across chat turns (WP6). Layer 2 is a stub that returns scripted scores: the rule is tested, not a
model, and no attack text is needed."""
import pytest

from firewall.orchestrator import FirewallOrchestrator
from firewall.session import CLEAN, EXPOSED
from firewall.turn_risk import TurnRisk, layer2_score


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_steady_benign_conversation_is_never_held():
    risk = TurnRisk()
    for score in [0.02, 0.05, 0.01, 0.1, 0.03, 0.2, 0.04, 0.06, 0.02, 0.05, 0.03, 0.01]:
        out = risk.record("s", score)
    assert not out["review"] and out["turns"] == 12


def test_three_borderline_turns_in_a_row_are_held_on_the_third():
    risk = TurnRisk(low=0.45, high=0.65)
    reviews = [risk.record("s", s)["review"] for s in (0.2, 0.5, 0.55, 0.6, 0.62)]
    assert reviews == [False, False, False, True, True]


def test_one_benign_turn_breaks_the_borderline_streak():
    risk = TurnRisk(low=0.45, high=0.65)
    for s in (0.5, 0.55, 0.05, 0.5, 0.55):
        out = risk.record("s", s)
    assert out["borderline_streak"] == 2 and not out["review"]


def test_turn_risk_weighs_recent_turns_more():
    risk = TurnRisk()
    for s in (0.99, 0.99, 0.05):
        out = risk.record("s", s)
    assert 0.5 < out["turn_risk"] < 0.7 and not out["review"]
    out = risk.record("s", 0.95)
    assert out["turn_risk"] >= 0.7 and out["review"] and out["reason"].startswith("turn_risk")


def test_sessions_are_separate_and_expire():
    clock = _Clock()
    risk = TurnRisk(ttl_seconds=60, clock=clock)
    for s in (0.5, 0.55, 0.6):
        risk.record("a", s)
    assert risk.info("a")["review"] and not risk.info("b")["review"]
    clock.now += 120
    assert risk.info("a")["turns"] == 0


def test_layer2_score_reads_the_trace():
    assert layer2_score({"trace": [{"layer": 1, "decision": "PASS"},
                                   {"layer": 2, "decision": "ALLOW", "details": {"max_window_score": 0.31}}]}) == 0.31
    assert layer2_score({"trace": [{"layer": 1, "decision": "BLOCK"}], "stopped_at_layer": 1, "decision": "BLOCK"}) == 1.0
    assert layer2_score({"trace": [{"layer": 2, "decision": "ALLOW", "confidence": 0.9}]}) == pytest.approx(0.1)


# ---------------------------------------------------------------- through the engine
class _ScriptedL2:
    """Returns the next scripted score: below `threshold` ALLOW, above BLOCK (like the real classifier's shape)."""
    threshold = 0.65

    def __init__(self, scores):
        self.scores = list(scores)

    def check(self, text, **_):
        score = self.scores.pop(0) if self.scores else 0.02
        if score >= self.threshold:
            return {"layer": 2, "decision": "BLOCK", "confidence": score, "reason": f"layer2_attack_score:{score:.3f}",
                    "details": {"max_window_score": score}}
        return {"layer": 2, "decision": "ALLOW", "confidence": 1 - score, "reason": f"layer2_low_risk:{score:.3f}",
                "details": {"max_window_score": score}}


class _PassL1:
    degraded = False
    index = None

    def check(self, text, **_):
        return {"layer": 1, "decision": "PASS", "confidence": 0.1, "reason": "low_similarity_no_match"}


def _engine(scores):
    return FirewallOrchestrator(layer1=_PassL1(), layer2=_ScriptedL2(scores))


def test_engine_holds_the_message_that_completes_a_borderline_run_and_exposes_the_session():
    engine = _engine([0.1, 0.5, 0.55, 0.6])
    decisions = [engine.process_input(f"lượt {i}", session_id="crescendo")["decision"] for i in range(4)]
    assert decisions == ["ALLOW", "ALLOW", "ALLOW", "REVIEW"]
    last = engine.process_input("lượt 5", session_id="crescendo")      # 0.02: the streak is broken
    assert last["decision"] == "ALLOW"
    assert engine.taint.level("crescendo") == EXPOSED
    assert engine.taint.exposure_sources("crescendo")[0]["source"] == "conversation"


def test_engine_held_turn_does_not_record_values_as_typed_by_the_user():
    engine = _engine([0.5, 0.55, 0.6])
    for text in ("a", "b", "chuyển vào 0451000999888"):
        out = engine.process_input(text, session_id="s")
    assert out["decision"] == "REVIEW" and out["final_reason"].startswith("session_risk:borderline_turns:3")
    assert engine.values.classify("s", "0451000999888")["origin"] != "trusted"


def test_no_session_no_session_risk():
    engine = _engine([0.5, 0.55, 0.6])
    outs = [engine.process_input("x") for _ in range(3)]
    assert all(o["decision"] == "ALLOW" and "session_risk" not in o for o in outs)
    assert engine.taint.level(None) == CLEAN
