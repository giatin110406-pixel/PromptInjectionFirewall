"""Agent LLM clients: OpenAI-compatible (local fake HTTP server, no network), local JSON protocol, scripted."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent.llm import (AgentLLMError, AssistantTurn, CallBudgetExceeded, LocalToolLLM, OpenAICompatToolLLM,
                       QuotaExhausted, ScriptedToolLLM, get_tool_llm, parse_local_reply)
from agent.tools import openai_tools


class FakeServer:
    """Answers POST /chat/completions with the next (status, headers, body) of `replies`; records the requests."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                       "body": json.loads(self.rfile.read(length))})
                status, headers, body = outer.replies.pop(0) if outer.replies else (500, {}, {"error": "no more replies"})
                data = json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def ok(message, finish="stop"):
    return 200, {}, {"choices": [{"message": message, "finish_reason": finish}]}


def tool_call(name, args, call_id="c1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def server():
    made = []

    def make(replies):
        s = FakeServer(replies)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def client(srv, **kw):
    kw.setdefault("sleep", lambda s: None)
    return OpenAICompatToolLLM("groq", model="m1", api_key="test-key", base_url=srv.url, **kw)


def test_parses_text_reply_and_sends_tools(server):
    srv = server([ok({"content": "Xin chào"})])
    turn = client(srv).chat([{"role": "user", "content": "hi"}], openai_tools(["refund"]))
    assert turn.text == "Xin chào" and not turn.tool_calls and turn.finish_reason == "stop"
    sent = srv.requests[0]
    assert sent["path"] == "/v1/chat/completions" and sent["auth"] == "Bearer test-key"
    assert sent["body"]["model"] == "m1" and sent["body"]["tools"][0]["function"]["name"] == "refund"


def test_parses_several_tool_calls(server):
    msg = {"content": None, "tool_calls": [tool_call("read_email", {"email_id": "latest"}, "a"),
                                           tool_call("lookup_order", {"order_id": "DH1"}, "b")]}
    srv = server([ok(msg, "tool_calls")])
    turn = client(srv).chat([{"role": "user", "content": "x"}], openai_tools())
    assert [c.name for c in turn.tool_calls] == ["read_email", "lookup_order"]
    assert turn.tool_calls[0].arguments == {"email_id": "latest"} and turn.finish_reason == "tool_calls"
    assert turn.to_message()["tool_calls"][1]["id"] == "b"


def test_bad_arguments_json_is_reported_not_raised(server):
    bad = {"id": "", "type": "function", "function": {"name": "refund", "arguments": "{not json"}}
    srv = server([ok({"content": "", "tool_calls": [bad]}, "tool_calls")])
    call = client(srv).chat([{"role": "user", "content": "x"}], openai_tools()).tool_calls[0]
    assert call.parse_error and call.arguments == {} and call.id      # a missing id (Gemini) is replaced


def test_429_is_retried_after_retry_after(server):
    srv = server([(429, {"retry-after": "3"}, {"error": "slow down"}), ok({"content": "ok"})])
    waits = []
    turn = client(srv, sleep=waits.append).chat([{"role": "user", "content": "x"}], [])
    assert turn.text == "ok" and waits == [3.0] and len(srv.requests) == 2


def test_daily_limit_429_stops_without_waiting(server):
    srv = server([(429, {"retry-after": "3600"}, {"error": "daily limit"})])
    waits = []
    with pytest.raises(QuotaExhausted):
        client(srv, sleep=waits.append).chat([{"role": "user", "content": "x"}], [])
    assert waits == [] and len(srv.requests) == 1


def test_persistent_429_raises_quota_exhausted(server):
    srv = server([(429, {}, {"error": "x"})] * 4)
    with pytest.raises(QuotaExhausted):
        client(srv, retries=2).chat([{"role": "user", "content": "x"}], [])
    assert len(srv.requests) == 3


def test_unknown_model_gives_a_clear_error(server):
    srv = server([(404, {}, {"error": {"message": "model_not_found"}})])
    with pytest.raises(AgentLLMError, match="AGENT_MODEL"):
        client(srv).chat([{"role": "user", "content": "x"}], [])
    assert len(srv.requests) == 1                        # not retried


def test_tool_use_failed_is_sampled_again(server):
    srv = server([(400, {}, {"error": {"code": "tool_use_failed"}}), ok({"content": "fine"})])
    assert client(srv).chat([{"role": "user", "content": "x"}], []).text == "fine"


def test_call_budget_counts_every_attempt(server):
    srv = server([ok({"content": "1"}), ok({"content": "2"}), ok({"content": "3"})])
    llm = client(srv, max_calls=2)
    llm.chat([{"role": "user", "content": "x"}], [])
    llm.chat([{"role": "user", "content": "x"}], [])
    with pytest.raises(CallBudgetExceeded):
        llm.chat([{"role": "user", "content": "x"}], [])
    assert len(srv.requests) == 2


def team_client(srv, monkeypatch, n=3, **kw):
    monkeypatch.setenv("GROQ_API_KEY", "key-1")
    for i in range(2, n + 1):
        monkeypatch.setenv(f"GROQ_API_KEY_{i}", f"key-{i}")
    kw.setdefault("sleep", lambda s: None)
    return OpenAICompatToolLLM("groq", model="m1", base_url=srv.url, **kw)


def test_daily_limit_moves_to_the_next_team_key(server, monkeypatch):
    srv = server([(429, {"retry-after": "3600"}, {"error": "daily limit"}), ok({"content": "ok"})])
    llm = team_client(srv, monkeypatch)
    assert llm.chat([{"role": "user", "content": "x"}], []).text == "ok"
    assert [r["auth"] for r in srv.requests] == ["Bearer key-1", "Bearer key-2"]
    # the next request stays on the key that worked
    srv.replies.append(ok({"content": "again"}))
    llm.chat([{"role": "user", "content": "y"}], [])
    assert srv.requests[-1]["auth"] == "Bearer key-2"


def test_all_team_keys_at_their_limit_raise_with_the_shortest_wait(server, monkeypatch):
    now = [1000.0]
    srv = server([(429, {"retry-after": "3600"}, {}), (429, {"retry-after": "600"}, {})])
    llm = team_client(srv, monkeypatch, n=2, clock=lambda: now[0])
    with pytest.raises(QuotaExhausted) as err:
        llm.chat([{"role": "user", "content": "x"}], [])
    assert err.value.retry_in == 600 and "[retry_in=600s]" in str(err.value) and len(srv.requests) == 2
    # once a key frees up it is used again
    now[0] += 601
    srv.replies.append(ok({"content": "back"}))
    assert llm.chat([{"role": "user", "content": "x"}], []).text == "back" and srv.requests[-1]["auth"] == "Bearer key-2"


def test_keys_are_read_in_numeric_order_without_duplicates(monkeypatch):
    from agent.llm import keys_from_env
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_10", "GROQ_API_KEY_3"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY_10", "d")
    monkeypatch.setenv("GROQ_API_KEY_2", "b")
    monkeypatch.setenv("GROQ_API_KEY_3", "a")
    assert keys_from_env("GROQ_API_KEY") == ["a", "b", "d"]


def test_missing_key_is_an_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(AgentLLMError, match="GROQ_API_KEY"):
        OpenAICompatToolLLM("groq")


# ---------------------------------------------------------------- local model
NAMES = ["refund", "read_email"]


def test_local_parses_a_tool_call():
    turn = parse_local_reply('Ok. {"tool": "refund", "arguments": {"order_id": "DH1", "amount": 5}} done', NAMES)
    assert turn.tool_calls[0].name == "refund" and turn.tool_calls[0].arguments["amount"] == 5


def test_local_parses_a_reply():
    assert parse_local_reply('{"reply": "Xong rồi"}', NAMES).text == "Xong rồi"


def test_local_broken_json_and_plain_text_are_text_replies():
    assert parse_local_reply('{"tool": "refund", "arguments": {', NAMES).text.startswith("{")
    turn = parse_local_reply("Chào bạn, mình giúp được gì?", NAMES)
    assert turn.text == "Chào bạn, mình giúp được gì?" and not turn.tool_calls


def test_local_unknown_tool_is_text():
    assert not parse_local_reply('{"tool": "format_disk", "arguments": {}}', NAMES).tool_calls


def test_local_llm_uses_the_generate_hook_without_loading_a_model():
    seen = {}

    def generate(prompt, system):
        seen.update(prompt=prompt, system=system)
        return '{"tool": "read_email", "arguments": {"email_id": "latest"}}'

    llm = LocalToolLLM(generate=generate)
    turn = llm.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "xem mail"}], openai_tools(["read_email"]))
    assert turn.tool_calls[0].name == "read_email" and "xem mail" in seen["prompt"] and "SYS" in seen["system"]
    assert llm._provider is None


# ---------------------------------------------------------------- scripted and factory
def test_scripted_plays_turns_then_finishes():
    llm = ScriptedToolLLM([{"tool": "read_email", "arguments": {"email_id": "m1"}}, {"calls": [
        {"tool": "refund", "arguments": {}}, {"tool": "lookup_order", "arguments": {}}]}, "đã xong"])
    t1, t2, t3, t4 = (llm.chat([], []) for _ in range(4))
    assert t1.tool_calls[0].name == "read_email" and len(t2.tool_calls) == 2 and t3.text == "đã xong" and t4.text == "Xong."
    assert llm.calls == 4 and isinstance(t4, AssistantTurn)


def test_factory_defaults_to_scripted_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    assert get_tool_llm().name == "scripted"
    with pytest.raises(AgentLLMError):
        get_tool_llm("nope")
