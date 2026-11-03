"""Bound waits and preserve tool/state integrity without spending external quota."""
import io
import json
import urllib.error

import pytest

from agent.llm import OpenAICompatToolLLM, QuotaExhausted, ScriptedToolLLM, get_tool_llm
from agent.loop import Agent
from firewall.deadline import DeadlineExceeded, check_deadline, turn_deadline


def test_interactive_rate_limit_returns_immediately_and_cooldown_avoids_another_request(monkeypatch):
    monkeypatch.setattr("agent.llm.load_env_file", lambda: 0)
    monkeypatch.setenv("GROQ_API_KEY", "agent-test-key")
    for name in list(__import__('os').environ):
        if name.startswith('GROQ_API_KEY_'):
            monkeypatch.delenv(name)
    client = get_tool_llm("groq", interactive=True)
    waits, requests = [], []
    client.sleep = waits.append

    def limited(request, timeout):
        requests.append(timeout)
        raise urllib.error.HTTPError(request.full_url, 429, "limited", {"retry-after": "3"}, io.BytesIO(b'{}'))

    client.opener = limited
    for _ in range(2):
        with pytest.raises(QuotaExhausted):
            client.chat([{"role": "user", "content": "hello"}], [])
    assert waits == [] and len(requests) == 1
    assert requests[0] <= 12 and client.calls == 1


def test_network_timeout_respects_the_remaining_turn_budget():
    observed = []
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    def opener(request, timeout):
        observed.append(timeout)
        return Reply()
    llm = OpenAICompatToolLLM("groq", api_key="test", opener=opener, timeout=60)
    with turn_deadline(0.5):
        assert llm.chat([{"role": "user", "content": "hi"}], []).text == "ok"
    assert 0 < observed[0] <= 0.5


def test_expired_turn_never_executes_a_late_model_tool_call(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("firewall.deadline.time.monotonic", lambda: now[0])
    class Slow(ScriptedToolLLM):
        def chat(self, *args):
            answer = super().chat(*args)
            now[0] += 40
            return answer
    llm = Slow([{"tool": "transfer_money", "arguments": {"to_account": "0451000123456", "bank_code": "VCB", "amount": 1000000}}])
    agent = Agent(llm=llm, mode="off")
    agent.reset("slow", "bank")
    out = agent.run("slow", "transfer")
    assert out.stopped == "timeout" and out.error_code == "timeout"
    assert not out.executed and out.backend_state["balances"]["0071000555666"] == 200000000


def test_timeout_closes_pending_tool_protocol_and_does_not_execute_the_next_action(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("firewall.deadline.time.monotonic", lambda: now[0])
    llm = ScriptedToolLLM([{"calls": [
        {"tool": "read_email", "arguments": {"email_id": "latest"}},
        {"tool": "transfer_money", "arguments": {"to_account": "0451000123456", "bank_code": "VCB", "amount": 1000000}},
    ]}])
    agent = Agent(llm=llm, mode="off")
    session = agent.reset("during-tool", "bank")
    def slow_read(*args):
        now[0] += 40
        return "hello"
    monkeypatch.setattr(session.backend, "read", slow_read)
    out = agent.run("during-tool", "read")
    assert out.stopped == "timeout" and not out.executed
    calls = {call["id"] for m in session.messages for call in m.get("tool_calls", [])}
    answered = {m["tool_call_id"] for m in session.messages if m["role"] == "tool"}
    assert calls == answered


def test_quota_is_reported_as_a_readable_reply_with_retry_delay():
    class Limited(ScriptedToolLLM):
        name = "groq"
        def chat(self, *args): raise QuotaExhausted("HTTP 429", retry_in=191)
    agent = Agent(llm=Limited([]), mode="off")
    agent.reset("quota", "shop")
    out = agent.run("quota", "hello")
    assert out.error_code == "rate_limit" and out.retry_after_seconds == 191
    assert "191" in out.reply and "giới hạn" in out.reply and "8000" not in out.reply


def test_deadline_scope_does_not_leak_to_the_next_request(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("firewall.deadline.time.monotonic", lambda: now[0])
    with turn_deadline(1):
        now[0] = 2
        with pytest.raises(DeadlineExceeded): check_deadline()
    check_deadline()
