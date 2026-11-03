"""Credential isolation and the Groq Judge wire contract, without external calls."""
import json

import pytest

from agent.llm import get_tool_llm
from firewall.groq_judge_provider import DEFAULT_JUDGE_MODEL, GroqJudgeProvider
from firewall.judge import build_judge_from_env, parse_verdict
from firewall.llm_provider import DEFAULT_GROQ_AGENT_MODEL, LLMError


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    monkeypatch.setattr("firewall.llm_provider.load_env_file", lambda *a, **k: 0)
    monkeypatch.setattr("agent.llm.load_env_file", lambda *a, **k: 0)
    monkeypatch.delenv("GROQ_JUDGE_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "agent-only-key")


def test_judge_never_uses_the_agent_key_as_a_fallback():
    with pytest.raises(LLMError, match="GROQ_JUDGE_API_KEY is not set"):
        GroqJudgeProvider()


@pytest.mark.parametrize("name", ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_5"])
def test_reusing_any_agent_key_is_refused(monkeypatch, name):
    monkeypatch.setenv(name, "same-key")
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "same-key")
    with pytest.raises(LLMError, match="must differ"):
        GroqJudgeProvider()


@pytest.mark.parametrize("explicit", [False, True])
def test_agent_model_cannot_be_reused(monkeypatch, explicit):
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    model = "custom-agent-model" if explicit else DEFAULT_GROQ_AGENT_MODEL
    if explicit:
        monkeypatch.setenv("AGENT_MODEL", model)
    with pytest.raises(LLMError, match="model"):
        GroqJudgeProvider(model=model)


def test_keys_and_models_are_independent_in_both_directions(monkeypatch):
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    judge = GroqJudgeProvider()
    agent = get_tool_llm("groq")
    assert judge.api_key == "judge-only-key" and agent.api_keys == ["agent-only-key"]
    assert judge.model == DEFAULT_JUDGE_MODEL and agent.model == DEFAULT_GROQ_AGENT_MODEL
    assert judge.model != agent.model


def test_factory_uses_the_dedicated_judge_settings(monkeypatch):
    monkeypatch.setenv("FIREWALL_JUDGE_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    monkeypatch.setenv("GROQ_JUDGE_MODEL", "judge-model")
    judge = build_judge_from_env()
    assert isinstance(judge.provider, GroqJudgeProvider)
    assert judge.provider.model == "judge-model"


def test_prompt_guard_cannot_be_mistaken_for_a_generative_judge(monkeypatch):
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    with pytest.raises(LLMError, match="classifier"):
        GroqJudgeProvider(model="meta-llama/llama-prompt-guard-2-86m")


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.body).encode()


def test_actual_request_uses_only_judge_credentials_and_structured_output(monkeypatch):
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    seen = {}

    def open_request(request, timeout):
        seen.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data))
        return Response({"choices": [{"message": {"content": '{"verdict":"benign","confidence":0.95}'},
                                      "finish_reason": "stop"}]})

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    verdict = GroqJudgeProvider().complete("Return JSON: judge this text", max_tokens=200)
    assert parse_verdict(verdict)["verdict"] == "benign"
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer judge-only-key"
    assert seen["headers"]["User-agent"] == "ai-firewall-judge/1.0"
    assert seen["body"]["model"] == DEFAULT_JUDGE_MODEL
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["max_completion_tokens"] > 200
    assert "tools" not in seen["body"]


@pytest.mark.parametrize("choice", [
    {"message": {"content": ""}, "finish_reason": "length"},
    {"message": {"content": '{"verdict":"benign"}'}, "finish_reason": "length"},
])
def test_truncated_or_empty_verdicts_fail_closed(monkeypatch, choice):
    monkeypatch.setenv("GROQ_JUDGE_API_KEY", "judge-only-key")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response({"choices": [choice]}))
    with pytest.raises(LLMError):
        GroqJudgeProvider().complete("JSON")
