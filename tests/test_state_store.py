"""Durable session state (WP10): SQLite write-through for taint/exposure, typed values and canaries."""
import json
import os

import pytest

from firewall.output_guard import OutputGuard
from firewall.review_queue import ReviewQueue
from firewall.session import CLEAN, EXPOSED, TAINTED, TaintStore
from firewall.state_store import ENV_VAR, StateStore
from firewall.values import TRUSTED, UNTRUSTED, ValueLedger


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "state.sqlite")


def test_store_basics(db):
    store = StateStore(db)
    store.put("ns", "a", {"x": [1, "ý"]}, 10.0)
    store.put("ns", "a", {"x": 2}, 11.0)
    store.put("ns", "b", 1, 5.0)
    assert store.get("ns", "a") == {"x": 2} and store.count("ns") == 2
    store.delete_older("ns", 6.0)
    assert store.get("ns", "b") is None and dict(store.items("ns")) == {"a": {"x": 2}}
    store.delete("ns")
    assert store.count("ns") == 0


def test_from_env_is_off_by_default(monkeypatch, db):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert StateStore.from_env() is None
    monkeypatch.setenv(ENV_VAR, db)
    assert StateStore.from_env().path == db


def test_taint_and_exposure_survive_a_restart(db):
    first = TaintStore(store=StateStore(db))
    first.expose("s1", "email", "m1", "ALLOW")
    first.mark("s2", "web", "layer2_attack_score:0.99", "p1")
    restarted = TaintStore(store=StateStore(db))           # a new process: nothing in memory
    assert restarted.level("s1") == EXPOSED and restarted.level("s2") == TAINTED and restarted.level("s3") == CLEAN
    assert restarted.exposure_sources("s1") == [{"source": "email", "chunk_id": "m1"}]
    assert sorted(restarted.exposed_sessions()) == ["s1", "s2"] and restarted.tainted_sessions() == ["s2"]


def test_two_processes_see_each_other(db):
    a, b = TaintStore(store=StateStore(db)), TaintStore(store=StateStore(db))
    assert b.level("s1") == CLEAN
    a.expose("s1", "rag", "kb1")
    assert b.level("s1") == EXPOSED
    b.clear("s1")
    assert a.level("s1") == CLEAN


def test_expiry_also_removes_the_durable_copy(db):
    clock = _Clock()
    store = StateStore(db)
    taint = TaintStore(ttl_seconds=60, clock=clock, store=store)
    taint.expose("old", "web", "p1")
    clock.now += 120
    assert taint.level("old") == CLEAN and store.get("session", "old") is None


def test_typed_values_survive_a_restart(db):
    first = ValueLedger(store=StateStore(db))
    first.add_trusted("s1", "chuyển 2 triệu vào 0451000999888")
    first.add_untrusted("s1", "STK mới: 0451000777666, phí 500.000đ", "email", "m1")
    restarted = ValueLedger(store=StateStore(db))
    assert restarted.classify("s1", "0451000999888")["origin"] == TRUSTED
    seen = restarted.classify("s1", "0451000777666")
    assert seen["origin"] == UNTRUSTED and seen["seen_in"] == [{"source": "email", "chunk_id": "m1"}]
    assert restarted.classify_amount("s1", 2_000_000)["origin"] == TRUSTED
    assert restarted.classify_amount("s1", 500_000)["origin"] == UNTRUSTED
    restarted.clear("s1")
    assert ValueLedger(store=StateStore(db)).classify("s1", "0451000999888")["origin"] != TRUSTED


def test_canary_survives_a_restart(db):
    token = OutputGuard(store=StateStore(db)).canary_for("s1")
    restarted = OutputGuard(store=StateStore(db))
    assert restarted.canary_for("s1") == token
    leak = restarted.check(f"mã nội bộ là {token}", session_id="s1")
    assert leak["decision"] == "BLOCK" and leak["findings"][0]["own_session"] is True


def test_memory_only_stores_are_unchanged():
    taint = TaintStore()
    taint.expose("s1", "web")
    assert taint.level("s1") == EXPOSED and TaintStore().level("s1") == CLEAN


def test_review_queue_is_shared_between_processes_and_written_atomically(tmp_path):
    path = str(tmp_path / "q.json")
    a, b = ReviewQueue(path), ReviewQueue(path)
    item = a.add("transfer_money", {"amount": 1}, "exposed_session:transfer_money", review_by="user")
    assert b.get(item["id"]) is not None                     # b reloads the file a wrote
    assert b.decide(item["id"], approve=False, reviewer="khach_hang")["status"] == "rejected"
    assert a.get(item["id"])["status"] == "rejected"
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert json.load(open(path, encoding="utf-8"))[0]["id"] == item["id"]


def test_engine_reports_where_session_state_lives(monkeypatch, db):
    from firewall.orchestrator import FirewallOrchestrator

    class _L2:
        def check(self, text):
            return {"layer": 2, "decision": "ALLOW", "confidence": 0.9}

    monkeypatch.setenv(ENV_VAR, db)
    engine = FirewallOrchestrator(layer2=_L2())
    engine.process_context([{"id": "c1", "text": "Lịch giao hàng thứ hai.", "source": "email"}], session_id="s9", use_judge=False)
    assert engine.health()["session_state"]["path"] == db
    monkeypatch.delenv(ENV_VAR)
    assert FirewallOrchestrator(layer2=_L2()).health()["session_state"]["path"] is None
    assert TaintStore(store=StateStore(db)).level("s9") == EXPOSED
