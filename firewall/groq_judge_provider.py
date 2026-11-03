"""A Groq judge with credentials/model isolated from the tool-calling Agent.

Prompt Guard is a classifier with a different response contract; it cannot be
used as the generative Layer3Judge without its own adapter.
"""
import os

from firewall.llm_provider import DEFAULT_GROQ_AGENT_MODEL, LLMError, OpenAICompatProvider, _post_json


DEFAULT_JUDGE_MODEL = "openai/gpt-oss-20b"


class GroqJudgeProvider(OpenAICompatProvider):
    name = "groq"

    def __init__(self, model=None, api_key=None, timeout=8.0, retries=0):
        key = (api_key if api_key is not None else os.environ.get("GROQ_JUDGE_API_KEY", "")).strip()
        if not key:
            raise LLMError("GROQ_JUDGE_API_KEY is not set; the Judge never falls back to Power Agent keys")
        agent_keys = {value.strip() for name, value in os.environ.items()
                      if name == "GROQ_API_KEY" or
                      (name.startswith("GROQ_API_KEY_") and name[len("GROQ_API_KEY_"):].isdigit())}
        if key in agent_keys:
            raise LLMError("GROQ_JUDGE_API_KEY must differ from every Power Agent GROQ_API_KEY and numbered fallback")
        selected = (model or os.environ.get("GROQ_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL).strip()
        if not selected:
            raise LLMError("GROQ_JUDGE_MODEL must name a generative Judge model")
        agent_model = (os.environ.get("AGENT_MODEL") or DEFAULT_GROQ_AGENT_MODEL).strip()
        if selected == agent_model:
            raise LLMError("GROQ_JUDGE_MODEL must differ from the Power Agent model")
        if "prompt-guard" in selected.casefold():
            raise LLMError("Prompt Guard is a classifier; select a generative LLM for the JSON-based Judge")
        super().__init__(model=selected, api_key=key, base_url="https://api.groq.com/openai/v1",
                         timeout=timeout, retries=retries)

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.0):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        payload = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"}}
        if self.model.startswith("openai/gpt-oss-"):
            # The small final JSON is separate from hidden reasoning; avoid exhausting
            # the completion budget before any verdict is produced.
            payload.update(reasoning_effort="low", max_completion_tokens=max_tokens + 2048)
        data = _post_json(self.base_url + "/chat/completions", payload,
                          {"Authorization": "Bearer " + self.api_key, "User-Agent": "ai-firewall-judge/1.0"},
                          self.timeout, self.retries)
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content")
        except (KeyError, IndexError, TypeError):
            raise LLMError("Groq Judge returned no valid message") from None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Groq Judge returned no final verdict (possibly exhausted reasoning tokens)")
        if choice.get("finish_reason") == "length":
            raise LLMError("Groq Judge verdict was truncated")
        return content
