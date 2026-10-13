import itertools

import pytest

from firewall.types import Decision, LayerResult, Source, max_decision, parse_decision


def test_decision_order_is_severity():
    assert Decision.ALLOW < Decision.SANITIZE < Decision.REVIEW < Decision.BLOCK


@pytest.mark.parametrize("combo", list(itertools.product(list(Decision), repeat=2)))
def test_max_decision_pairs(combo):
    a, b = combo
    assert max_decision(a, b) == (a if a >= b else b)


def test_max_decision_accepts_iterable_and_empty():
    assert max_decision([Decision.ALLOW, Decision.REVIEW]) == Decision.REVIEW
    assert max_decision() == Decision.ALLOW
    assert max_decision([]) == Decision.ALLOW


@pytest.mark.parametrize("raw,expected", [
    ("ALLOW", Decision.ALLOW),
    ("PASS", Decision.ALLOW),
    ("pass", Decision.ALLOW),
    ("SANITIZE", Decision.SANITIZE),
    ("REVIEW", Decision.REVIEW),
    ("BLOCK", Decision.BLOCK),
    (Decision.BLOCK, Decision.BLOCK),
])
def test_parse_decision_known(raw, expected):
    assert parse_decision(raw) == expected


@pytest.mark.parametrize("raw", ["ESCALATE", "garbage", "", None, 3])
def test_parse_decision_non_final_returns_none(raw):
    assert parse_decision(raw) is None


def test_layer_result_round_trip_keeps_legacy_fields_and_extras():
    raw = {
        "layer": 1, "decision": "BLOCK", "reason": "regex_match:x", "confidence": 1.0,
        "matched_pattern": "x", "matched_view": "raw", "latency_ms": 0.2,
    }
    out = LayerResult.from_dict(raw).to_dict()
    for key in ("layer", "decision", "confidence", "reason", "latency_ms", "matched_pattern", "matched_view"):
        assert out[key] == raw[key]
    assert out["degraded"] is False


def test_layer_result_defaults_for_sparse_input():
    out = LayerResult.from_dict({"layer": 2, "decision": "ALLOW"}).to_dict()
    assert out["confidence"] == 0.0 and out["reason"] == "" and out["degraded"] is False


def test_layer_result_preserves_degraded_flag():
    assert LayerResult.from_dict({"layer": 3, "decision": "REVIEW", "degraded": True}).degraded is True


def test_source_values():
    assert {s.value for s in Source} == {"USER", "UNTRUSTED", "SYSTEM"}
