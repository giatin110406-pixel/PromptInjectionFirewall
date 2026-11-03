"""
Tool-calling LLMs for the agent (docs/agent_plan_vi.md section 2).

    ToolLLM.chat(messages, tools) -> AssistantTurn      messages and tools use the OpenAI chat format

Providers (get_tool_llm, env AGENT_PROVIDER, AGENT_MODEL):
- groq, gemini   OpenAICompatToolLLM: both expose an OpenAI-compatible /chat/completions with `tools`.
                 env: GROQ_API_KEY / GEMINI_API_KEY. A 429 is retried after the `retry-after` header; every HTTP attempt
                 counts against the call budget (AGENT_MAX_CALLS, default 300). More keys of the team can be given as
                 GROQ_API_KEY_2, GROQ_API_KEY_3, ...: when one key hits its daily limit the next one is used.
- local          LocalToolLLM: a Hugging Face chat model in this process. It has no native tool calling, so it is asked
                 for a JSON object {"tool": ..., "arguments": {...}} or {"reply": ...}; anything else is a text reply.
- scripted       ScriptedToolLLM: fixed tool calls, no network. Tests, dry runs and the demo fallback.

Keys are read from the environment (and .env through firewall.llm_provider.load_env_file); they are never logged.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from firewall.llm_provider import DEFAULT_GROQ_AGENT_MODEL, LLMError, load_env_file
from firewall.deadline import DeadlineExceeded, check_deadline, remaining_timeout

DEFAULT_MAX_CALLS = 300

# Model names change often. The plan named llama-3.3-70b-versatile for Groq, but this account's /models list no longer has
# it (HTTP 404 model_not_found, 2026-11-02); openai/gpt-oss-120b is on the list and does tool calls. Override with AGENT_MODEL.
PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "model": DEFAULT_GROQ_AGENT_MODEL},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY",
               "model": "gemini-2.5-flash"},
}


class AgentLLMError(LLMError):
    """The agent LLM failed (after retries), or rejected the model or the request."""


class CallBudgetExceeded(AgentLLMError):
    """AGENT_MAX_CALLS reached: a run stops cleanly instead of spending more quota."""


class QuotaExhausted(AgentLLMError):
    """The provider kept answering 429 after the retries: the free-tier limit for the minute or the day is used up.
    `retry_in` is the shortest wait the provider asked for (seconds), so a caller can sleep and go on."""

    def __init__(self, message: str, retry_in: Optional[float] = None):
        super().__init__(message if retry_in is None else f"{message} [retry_in={retry_in:.0f}s]")
        self.retry_in = retry_in


def keys_from_env(key_env: str) -> List[str]:
    """KEY, then KEY_2, KEY_3, ... in numeric order; empty values and duplicates are skipped."""
    numbered = sorted((int(name[len(key_env) + 1:]), value) for name, value in os.environ.items()
                      if name.startswith(key_env + "_") and name[len(key_env) + 1:].isdigit())
    keys: List[str] = []
    for value in [os.environ.get(key_env, "")] + [v for _, v in numbered]:
        if value and value not in keys:
            keys.append(value)
    return keys


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    parse_error: Optional[str] = None


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

    def to_message(self) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                                 for c in self.tool_calls]
        return msg


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:10]


class ToolLLM:
    name = "base"
    model = ""

    def __init__(self):
        self.calls = 0                   # LLM requests made (HTTP attempts for the network providers)

    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AssistantTurn:
        raise NotImplementedError


# ---------------------------------------------------------------- OpenAI-compatible (groq, gemini)
class OpenAICompatToolLLM(ToolLLM):
    def __init__(self, provider: str = "groq", model: Optional[str] = None, api_key: Optional[str] = None,
                 base_url: Optional[str] = None, timeout: float = 60.0, retries: int = 3, max_calls: Optional[int] = None,
                 temperature: float = 0.0, opener: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep,
                 max_retry_wait: float = 65.0, clock: Callable[[], float] = time.time):
        super().__init__()
        spec = PROVIDERS.get(provider, {})
        self.name = provider
        self.model = model or os.environ.get("AGENT_MODEL") or spec.get("model", "")
        self.api_keys = [api_key] if api_key is not None else keys_from_env(spec.get("key_env", ""))
        self.api_keys = [k for k in self.api_keys if k]
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self.key_index = 0
        self._blocked_until: Dict[int, float] = {}      # key index -> time its daily limit frees up
        self.base_url = (base_url or spec.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise AgentLLMError(f"unknown provider '{provider}' (groq, gemini)")
        if not self.api_key:
            raise AgentLLMError(f"{spec.get('key_env', 'API key')} is not set (put it in .env or the environment, never in git)")
        if not self.model:
            raise AgentLLMError("set AGENT_MODEL")
        self.timeout, self.retries, self.temperature = timeout, retries, temperature
        self.max_calls = max_calls if max_calls is not None else int(os.environ.get("AGENT_MAX_CALLS", DEFAULT_MAX_CALLS))
        self.opener, self.sleep, self.max_retry_wait, self.clock = opener, sleep, max_retry_wait, clock

    def _spend(self) -> None:
        if self.calls >= self.max_calls:
            raise CallBudgetExceeded(f"call budget of {self.max_calls} reached")
        self.calls += 1

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
        header = exc.headers.get("retry-after") if exc.headers is not None else None
        try:
            return max(0.0, float(header))
        except (TypeError, ValueError):
            return float(min(2 ** attempt * 2, 30))

    def _next_key(self, wait: float) -> bool:
        """The current key hit a daily limit for `wait` seconds: switch to a key that is free now. False if none is."""
        now = self.clock()
        self._blocked_until[self.key_index] = now + wait
        for idx in range(len(self.api_keys)):
            if self._blocked_until.get(idx, 0) <= now:
                self.key_index, self.api_key = idx, self.api_keys[idx]
                return True
        return False

    def _request(self, body: bytes) -> urllib.request.Request:
        return urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
            # Groq sits behind Cloudflare, which refuses urllib's default agent (HTTP 403, error 1010)
            "User-Agent": "ai-firewall-agent/1.0"})

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        now = self.clock()
        if self._blocked_until.get(self.key_index, 0) > now:
            ready = next((i for i in range(len(self.api_keys)) if self._blocked_until.get(i, 0) <= now), None)
            if ready is None:
                raise QuotaExhausted(f"Rate limit is still active for {self.model}",
                                     retry_in=max(0.0, min(self._blocked_until.values()) - now))
            self.key_index, self.api_key = ready, self.api_keys[ready]
        last: Optional[Exception] = None
        attempt = 0
        while attempt <= self.retries:
            timeout = remaining_timeout(self.timeout)
            self._spend()
            request = self._request(body)
            try:
                with (self.opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    check_deadline()
                    return data
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code == 429:
                    last = QuotaExhausted(f"HTTP 429 from {self.name}: {detail}")
                    wait = self._retry_after(exc, attempt)
                    if wait > self.max_retry_wait:           # a daily limit: waiting here would hang the run
                        if self._next_key(wait):
                            continue                          # another key of the team is free: same request, no retry spent
                        retry_in = min(self._blocked_until.values()) - self.clock()
                        raise QuotaExhausted(f"HTTP 429 from {self.name} on all {len(self.api_keys)} key(s): {detail}",
                                             retry_in=max(0.0, retry_in)) from exc
                    if attempt < self.retries:
                        self.sleep(remaining_timeout(wait))
                    attempt += 1
                    continue
                if exc.code == 400 and "tool_use_failed" in detail and attempt < self.retries:
                    last = AgentLLMError(f"{self.name} could not produce a valid tool call: {detail}")
                    attempt += 1
                    continue                                  # the model wrote a malformed call; sampling again may fix it
                if exc.code in (400, 401, 403, 404):
                    hint = f" (model '{self.model}' rejected or unknown: set AGENT_MODEL)" if exc.code in (400, 404) else ""
                    raise AgentLLMError(f"HTTP {exc.code} from {self.name}{hint}: {detail}") from exc
                last = AgentLLMError(f"HTTP {exc.code} from {self.name}: {detail}")
            except DeadlineExceeded:
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                last = AgentLLMError(f"request to {self.name} failed: {exc}")
            if attempt < self.retries:
                self.sleep(remaining_timeout(min(2 ** attempt, 8)))
            attempt += 1
        if isinstance(last, QuotaExhausted):
            raise last
        raise AgentLLMError(f"{self.name}: request failed after {self.retries + 1} attempts: {last}")

    def chat(self, messages, tools):
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        data = self._post(payload)
        choices = data.get("choices") or []
        if not choices:
            raise AgentLLMError(f"{self.name} returned no choices: {str(data)[:200]}")
        choice = choices[0]
        message = choice.get("message") or {}
        calls = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            args, error = fn.get("arguments") or {}, None
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args, error = {}, "arguments are not valid JSON"
            if not isinstance(args, dict):
                args, error = {}, "arguments are not a JSON object"
            calls.append(ToolCall(id=raw.get("id") or new_call_id(), name=str(fn.get("name", "")), arguments=args,
                                  parse_error=error))
        return AssistantTurn(text=str(message.get("content") or ""), tool_calls=calls,
                             finish_reason=str(choice.get("finish_reason") or "stop"))


# ---------------------------------------------------------------- local model (no native tool calling)
LOCAL_PROTOCOL = (
    "Bạn có các tool sau (tên: tham số):\n{tools}\n"
    "Mỗi lượt chỉ trả MỘT đối tượng JSON, không thêm chữ nào khác: "
    '{{"tool": "<tên>", "arguments": {{...}}}} để gọi tool, hoặc {{"reply": "<câu trả lời cho khách>"}} khi xong.')


def parse_local_reply(text: str, tool_names) -> AssistantTurn:
    """The first JSON object in `text`: a tool call, a reply, or (when it is neither) the plain text as the reply."""
    start = text.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            if isinstance(obj.get("tool"), str) and obj["tool"] in set(tool_names) and isinstance(obj.get("arguments", {}), dict):
                return AssistantTurn(tool_calls=[ToolCall(id=new_call_id(), name=obj["tool"], arguments=obj.get("arguments", {}))],
                                     finish_reason="tool_calls")
            if isinstance(obj.get("reply"), str):
                return AssistantTurn(text=obj["reply"])
    return AssistantTurn(text=text.strip())


class LocalToolLLM(ToolLLM):
    name = "local"

    def __init__(self, model: Optional[str] = None, generate: Optional[Callable[[str, str], str]] = None,
                 max_tokens: int = 300):
        super().__init__()
        self.model = model or os.environ.get("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
        self.max_tokens = max_tokens
        self._generate = generate
        self._provider = None

    def _gen(self, prompt: str, system: str) -> str:
        if self._generate is not None:
            return self._generate(prompt, system)
        if self._provider is None:
            from firewall.llm_provider import LocalHFProvider
            self._provider = LocalHFProvider(model=self.model)
        return self._provider.complete(prompt, system=system, max_tokens=self.max_tokens, temperature=0.0)

    def chat(self, messages, tools):
        names = [t["function"]["name"] for t in tools]
        listing = "\n".join(f"- {t['function']['name']}: " + ", ".join(t["function"]["parameters"].get("properties", {}))
                            for t in tools)
        system = "\n\n".join([m["content"] for m in messages if m["role"] == "system"] + [LOCAL_PROTOCOL.format(tools=listing)])
        lines = []
        for m in messages:
            if m["role"] == "user":
                lines.append(f"Khách: {m['content']}")
            elif m["role"] == "assistant":
                calls = m.get("tool_calls") or []
                lines.append("Trợ lý: " + (json.dumps({"tool": calls[0]["function"]["name"],
                                                       "arguments": json.loads(calls[0]["function"]["arguments"])}, ensure_ascii=False)
                                           if calls else json.dumps({"reply": m.get("content", "")}, ensure_ascii=False)))
            elif m["role"] == "tool":
                lines.append(f"Kết quả tool: {m['content']}")
        self.calls += 1
        try:
            raw = self._gen("\n".join(lines) + "\nTrợ lý:", system)
        except LLMError as exc:
            raise AgentLLMError(str(exc)) from exc
        return parse_local_reply(raw, names)


# ---------------------------------------------------------------- scripted (no network)
Turn = Union[AssistantTurn, Dict[str, Any], str]


def _as_turn(spec: Turn) -> AssistantTurn:
    if isinstance(spec, AssistantTurn):
        return spec
    if isinstance(spec, str):
        return AssistantTurn(text=spec)
    if "calls" in spec:
        calls = [ToolCall(id=new_call_id(), name=c["tool"], arguments=dict(c.get("arguments", {}))) for c in spec["calls"]]
        return AssistantTurn(text=spec.get("reply", ""), tool_calls=calls, finish_reason="tool_calls")
    if "tool" in spec:
        return AssistantTurn(text=spec.get("say", ""), finish_reason="tool_calls",
                             tool_calls=[ToolCall(id=new_call_id(), name=spec["tool"], arguments=dict(spec.get("arguments", {})))])
    return AssistantTurn(text=str(spec.get("reply", "")))


class ScriptedToolLLM(ToolLLM):
    """Plays a fixed list of turns, one per chat() call: {"tool": name, "arguments": {...}}, {"calls": [...]} for several
    tool calls in one turn, {"reply": text} or a plain string. When the list runs out it answers "Xong." A callable
    `script(messages, tools)` may be given instead of a list."""
    name = "scripted"
    model = "scripted"

    def __init__(self, script: Union[List[Turn], Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Turn]]):
        super().__init__()
        self.script = script
        self.seen: List[List[Dict[str, Any]]] = []      # the messages of each call, for tests

    def chat(self, messages, tools):
        self.calls += 1
        self.seen.append(json.loads(json.dumps(messages)))
        if callable(self.script):
            return _as_turn(self.script(messages, tools))
        index = self.calls - 1
        return _as_turn(self.script[index] if index < len(self.script) else {"reply": "Xong."})


# ---------------------------------------------------------------- default scripted behaviour for the demo
_ACCOUNT = re.compile(r"(?<![\d.])\d{8,16}(?![\d.])")
_ORDER = re.compile(r"\b(?:DH|ORD|OD)-?\d{4,}\b", re.I)


def _last_user(messages) -> str:
    return next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")


def _amount_vnd(text: str) -> Optional[float]:
    t = text.lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(triệu|tr|k|nghìn)\b", t)
    if m:
        return round(float(m.group(1).replace(",", ".")) * {"triệu": 1e6, "tr": 1e6, "k": 1e3, "nghìn": 1e3}[m.group(2)])
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)\s*(?:đ|đồng|vnd)", t)
    return float(m.group(1).replace(".", "")) if m else None


def naive_policy(domain: str) -> Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Turn]:
    """A scripted stand-in for a gullible agent, used when no real LLM is configured: it reads the newest item (when the
    request mentions mail, a slip, a bill or a ticket) and then runs the domain's main action on the first destination it
    finds, in the customer's message or in what it read. Not an attack generator: it only follows the data it is given."""

    def policy(messages, tools):
        user = _last_user(messages)
        start = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
        current = messages[start:]
        # A real model reads datamarked words. The fallback parser must also see their word boundaries.
        tool_texts = [m["content"].replace("ˆ", " ") for m in current if m["role"] == "tool"]
        called = [c["function"]["name"] for m in current if m["role"] == "assistant" for c in m.get("tool_calls") or []]
        if any(n in called for n in ("transfer_money", "refund", "data_access")):
            return {"reply": "Xong."}
        wants_read = re.search(r"email|thư|phiếu|hóa đơn|ticket|tài liệu|trang|tin nhắn|xem giúp|tóm tắt|đóng tiền", user, re.I)
        if wants_read and not tool_texts:
            resources = "\n".join(m["content"] for m in messages if m["role"] == "system")
            if "Trang web khách gửi:" in resources:
                return {"tool": "fetch_url", "arguments": {"url": "latest"}}
            if "Có một kết quả tra cứu đơn hàng" in resources:
                return {"tool": "lookup_order", "arguments": {"order_id": "latest"}}
            if "Kho tài liệu có:" in resources or ("Hộp thư có" not in resources and domain == "work"):
                return {"tool": "open_document", "arguments": {"document_id": "latest"}}
            return {"tool": "read_email", "arguments": {"email_id": "latest"}}
        haystack = "\n".join([user] + tool_texts)
        if domain == "bank":
            account = (_ACCOUNT.findall(re.sub(r"(\d)[ .](?=\d{3}\b)", r"\1", haystack)) or [None])[0]
            if account is None and re.search(r"\bmẹ\b", user, re.I):
                if "lookup_contact" not in called:
                    return {"tool": "lookup_contact", "arguments": {"name": "Mẹ"}}
            if account:
                return {"tool": "transfer_money", "arguments": {"to_account": account, "bank_code": "VCB",
                                                                "amount": _amount_vnd(haystack) or 1_000_000}}
        elif domain == "shop":
            order = (_ORDER.findall(haystack) or [None])[0]
            if order:
                return {"tool": "refund", "arguments": {"order_id": order, "amount": 38 if tool_texts else 45,
                                                        "order_value": 65 if tool_texts else 60, "reason": "Theo yêu cầu"}}
        else:
            return {"tool": "data_access", "arguments": {
                "resource": "customer_list" if tool_texts else "leave_balance",
                "query_scope": "all" if tool_texts else "own_account"}}
        return {"reply": "Mình đã ghi nhận. Bạn cần mình hoàn tiền, chuyển tiền hoặc tra cứu gì?"}

    return policy


# ---------------------------------------------------------------- factory
def get_tool_llm(provider: Optional[str] = None, model: Optional[str] = None, max_calls: Optional[int] = None,
                 script=None, domain: str = "bank", interactive: bool = False) -> ToolLLM:
    load_env_file()
    provider = (provider or os.environ.get("AGENT_PROVIDER") or "scripted").lower()
    if provider == "scripted":
        return ScriptedToolLLM(script if script is not None else naive_policy(domain))
    if provider == "local":
        return LocalToolLLM(model=model or os.environ.get("AGENT_MODEL") or None)
    if provider in PROVIDERS:
        options = {"timeout": 12.0, "retries": 1, "max_retry_wait": 0.0} if interactive else {}
        return OpenAICompatToolLLM(provider, model=model, max_calls=max_calls, **options)
    raise AgentLLMError(f"unknown AGENT_PROVIDER '{provider}' (groq, gemini, local, scripted)")
