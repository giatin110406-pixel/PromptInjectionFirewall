"""
Minimal, dependency-free LLM access shared by the data generator (P2-T4) and, later,
the Layer 3 judge (P5-T3).

Providers (select with get_provider):
- ollama      local model, no key.            env: OLLAMA_URL (default http://localhost:11434)
- anthropic   Anthropic Messages API.         env: ANTHROPIC_API_KEY, ANTHROPIC_MODEL
- openai      any OpenAI-compatible endpoint. env: OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
- deepseek    DeepSeek (OpenAI-compatible).    env: DEEPSEEK_API_KEY, DEEPSEEK_MODEL (default deepseek-flash)
- manual      no API: prompts are written to a folder, a human pastes them into a chat UI
              and saves the replies; a second run reads them back.
- fake        deterministic stub for tests.

Network providers use urllib only and retry with backoff. A `BudgetedProvider` wrapper
enforces a hard cap on calls so a bug cannot run up a bill.

None of the network providers has been exercised against a live service in this repository's
tests; they are covered with a local fake HTTP server.
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class LLMError(RuntimeError):
    """The provider failed after retries."""


class ManualPending(Exception):
    """Manual mode: the prompt was recorded; there is no answer yet."""

    def __init__(self, request_id: str):
        super().__init__(request_id)
        self.request_id = request_id


class BudgetExceeded(LLMError):
    pass


def prompt_id(prompt: str, system: Optional[str] = None) -> str:
    return hashlib.sha256(f"{system or ''}\n---\n{prompt}".encode("utf-8")).hexdigest()[:16]


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None, max_tokens: int = 1024,
                 temperature: float = 0.7) -> str:
        """Return the model's text reply."""


def _post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float,
               retries: int, opener: Optional[Callable] = None) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 404):  # retrying will not help
                raise LLMError(f"HTTP {exc.code} from {url}: {exc.read().decode('utf-8', 'replace')[:200]}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))
    raise LLMError(f"request to {url} failed after {retries + 1} attempts: {last}")


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str = "qwen2.5:7b", base_url: Optional[str] = None,
                 timeout: float = 120.0, retries: int = 2):
        self.model = model
        self.base_url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout, self.retries = timeout, retries

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        payload: Dict[str, Any] = {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        data = _post_json(f"{self.base_url}/api/generate", payload, {}, self.timeout, self.retries)
        return str(data.get("response", ""))


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: str = "https://api.anthropic.com", timeout: float = 60.0, retries: int = 2):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.base_url, self.timeout, self.retries = base_url.rstrip("/"), timeout, retries
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        payload: Dict[str, Any] = {
            "model": self.model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = _post_json(f"{self.base_url}/v1/messages", payload, headers, self.timeout, self.retries)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


class GeminiProvider(LLMProvider):
    """
    Google AI Studio (Gemini API), REST. Needs GEMINI_API_KEY (or GOOGLE_API_KEY): a free key from
    https://aistudio.google.com. Nothing is sent unless a key is set. Model names change often, so the
    default can be overridden with GEMINI_MODEL.
    """
    name = "gemini"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: str = "https://generativelanguage.googleapis.com", timeout: float = 30.0, retries: int = 1,
                 opener: Optional[Callable] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.base_url, self.timeout, self.retries, self.opener = base_url.rstrip("/"), timeout, retries, opener
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set (put it in .env or the environment, never in git)")

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        generation: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens,
                                      "responseMimeType": "application/json"}
        if self.model.startswith("gemini-2.5"):
            generation["thinkingConfig"] = {"thinkingBudget": 0}   # otherwise thinking tokens eat max_tokens
        payload: Dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                                   "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = _post_json(f"{self.base_url}/v1beta/models/{self.model}:generateContent", payload,
                          {"x-goog-api-key": self.api_key}, self.timeout, self.retries, opener=self.opener)
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"Gemini returned no candidates: {str(data)[:200]}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text:
            raise LLMError(f"Gemini returned an empty answer (finishReason={candidates[0].get('finishReason')})")
        return text


class OpenAICompatProvider(LLMProvider):
    name = "openai"
    reasoning_headroom = 0  # extra tokens for models that "think" before answering

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: float = 60.0, retries: int = 2):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout, self.retries = timeout, retries
        self.extra_payload: Dict[str, Any] = {}  # provider-specific request fields
        if not self.model:
            raise LLMError("set OPENAI_MODEL (or pass --model)")

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        payload = {"model": self.model, "messages": messages,
                   "max_tokens": max_tokens + self.reasoning_headroom, "temperature": temperature,
                   **self.extra_payload}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = _post_json(f"{self.base_url}/chat/completions", payload, headers, self.timeout, self.retries)
        choice = data["choices"][0]
        content = str(choice["message"].get("content") or "")
        if not content.strip() and choice.get("finish_reason") == "length":
            # Reasoning models spend max_tokens on hidden reasoning first. An empty reply here is a
            # truncation, not an answer: fail loudly instead of returning "" to the caller.
            raise LLMError(f"{self.name}: reply truncated before any content (max_tokens too small for a reasoning model)")
        return content


class DeepSeekProvider(OpenAICompatProvider):
    """
    DeepSeek speaks the OpenAI chat-completions protocol. Model names change between
    releases (deepseek-chat was retired in favour of deepseek-flash / deepseek-v4-pro), so
    set DEEPSEEK_MODEL or pass --model if the default is rejected. Check the current list at
    https://api-docs.deepseek.com/ before a long run.
    """
    name = "deepseek"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: float = 90.0, retries: int = 2,
                 thinking: bool = False):
        """
        `thinking=False` (default) sends {"thinking": {"type": "disabled"}}. Data generation does not
        need reasoning, and with reasoning on, deepseek-flash spent max_tokens on hidden thinking and
        returned empty replies (4 of 14 calls in the first pilot). With `thinking=True` the provider
        adds 2048 tokens of headroom so the answer still fits.
        """
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise LLMError("DEEPSEEK_API_KEY is not set (put it in .env or the environment, never in git)")
        super().__init__(
            model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
            api_key=key,
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=timeout, retries=retries,
        )
        self.thinking = thinking
        if thinking:
            self.reasoning_headroom = 2048
        else:
            self.extra_payload = {"thinking": {"type": "disabled"}}


class ManualProvider(LLMProvider):
    """
    No API. First run: every prompt is appended to `requests.jsonl` (and a readable
    `requests.md`) and ManualPending is raised. A human pastes each prompt into any chat UI
    and appends the reply to `answers.jsonl` as {"id": "<request id>", "text": "<reply>"}.
    Second run: replies are read back, so the same code path works with or without an API.
    """
    name = "manual"

    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)
        self.requests_path = os.path.join(directory, "requests.jsonl")
        self.answers_path = os.path.join(directory, "answers.jsonl")
        self._answers = self._load_answers()
        self._recorded = self._load_recorded()

    def _load_answers(self) -> Dict[str, str]:
        answers: Dict[str, str] = {}
        if os.path.exists(self.answers_path):
            with open(self.answers_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        answers[str(item["id"])] = str(item["text"])
        return answers

    def _load_recorded(self) -> set:
        if not os.path.exists(self.requests_path):
            return set()
        with open(self.requests_path, "r", encoding="utf-8") as handle:
            return {json.loads(line)["id"] for line in handle if line.strip()}

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        request_id = prompt_id(prompt, system)
        if request_id in self._answers:
            return self._answers[request_id]
        if request_id not in self._recorded:
            record = {"id": request_id, "system": system, "prompt": prompt}
            with open(self.requests_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            with open(os.path.join(self.directory, "requests.md"), "a", encoding="utf-8") as handle:
                handle.write(f"\n\n## {request_id}\n\n" + (f"[system] {system}\n\n" if system else "") + prompt + "\n")
            self._recorded.add(request_id)
        raise ManualPending(request_id)


class FakeProvider(LLMProvider):
    """Deterministic stand-in for tests: `reply` is a string or a callable(prompt) -> str."""
    name = "fake"

    def __init__(self, reply: Any = "ok"):
        self.reply = reply
        self.calls = 0

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        self.calls += 1
        return self.reply(prompt) if callable(self.reply) else str(self.reply)


class BudgetedProvider(LLMProvider):
    """Hard cap on the number of calls, so a loop bug cannot spend without limit."""

    def __init__(self, inner: LLMProvider, max_calls: int):
        self.inner, self.max_calls, self.calls = inner, max_calls, 0
        self.name = inner.name
        self._lock = threading.Lock()  # the generator calls this from several threads

    def complete(self, prompt, system=None, max_tokens=1024, temperature=0.7):
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"call budget of {self.max_calls} reached")
            self.calls += 1
        return self.inner.complete(prompt, system, max_tokens, temperature)


def load_env_file(path: Optional[str] = None) -> int:
    """
    Read KEY=VALUE lines from a .env file into os.environ without overriding values that are
    already set. Returns how many variables were added. The file is git-ignored; keys must
    never be committed.
    """
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return 0
    added = 0
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
                added += 1
    return added


def get_provider(name: str, model: Optional[str] = None, manual_dir: Optional[str] = None,
                 max_calls: Optional[int] = None) -> LLMProvider:
    load_env_file()
    name = name.lower()
    if name == "ollama":
        provider: LLMProvider = OllamaProvider(model=model or "qwen2.5:7b")
    elif name == "gemini":
        provider = GeminiProvider(model=model)
    elif name == "anthropic":
        provider = AnthropicProvider(model=model)
    elif name == "openai":
        provider = OpenAICompatProvider(model=model)
    elif name == "deepseek":
        provider = DeepSeekProvider(model=model)
    elif name == "manual":
        if not manual_dir:
            raise LLMError("manual provider needs --manual-dir")
        provider = ManualProvider(manual_dir)
    else:
        raise LLMError(f"unknown provider '{name}' (ollama, gemini, anthropic, openai, deepseek, manual)")
    return BudgetedProvider(provider, max_calls) if max_calls else provider
