"""
Layer 3: LLM judge. A second reader for the cases Layer 2 is unsure about.

Layer 2's score is bimodal: almost every text scores near 0 or near 1, so the useful work for a judge is at two edges:
  side "allow"  score from `escalate_low` up to the block threshold: Layer 2 let it through, but only just;
  side "block"  score from the block threshold up to `escalate_high`: Layer 2 blocked it, but not with confidence.
Measured on dataset_v2: about half of Layer 2's false blocks sit in the second edge.

What the judge may change (see `resolve`):
  side allow : attack -> BLOCK | benign (confident) -> ALLOW | anything else -> REVIEW
  side block : attack -> BLOCK | benign (confident) -> REVIEW (never ALLOW: a hijacked judge must not unblock an
               attack by itself; set `downgrade_to="ALLOW"` to accept that risk) | anything else -> BLOCK
A judge that fails (no provider, timeout, bad JSON, budget spent) never weakens a decision: on the allow side the
answer is REVIEW, on the block side the block stays. Failures are flagged `degraded` so /health and the trace show them.

The text under judgement may itself contain instructions aimed at the judge. It is placed between two random marker
lines (a fresh nonce per call, so the text cannot close them), the prompt says to treat it as data, and the reply must
be one JSON object; anything else is a failure, not a verdict.
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

from firewall.llm_provider import LLMError, LLMProvider, ManualPending

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "judge_v1.md")
PROMPT_VERSION = "judge_v1"
MAX_TEXT_CHARS = 3000
JUDGE_TIMEOUT_SECONDS = 8.0
VERDICTS = {"attack", "benign", "unsure"}

SOURCE_TEXT = {
    "user": "a message typed by a user",
    "untrusted": "content fetched from outside (an email, web page, retrieved document or tool result)",
}


class DailyBudget:
    """At most `limit` provider calls per calendar day (local time). Protects a free-tier key and a wallet alike."""

    def __init__(self, limit: int, clock=time.time):
        self.limit, self._clock = limit, clock
        self._day, self._used = None, 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            today = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
            if today != self._day:
                self._day, self._used = today, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        return self._used


def parse_verdict(raw: str) -> Dict[str, Any]:
    """The judge's reply as {verdict, confidence, category, reason}. Raises ValueError on anything else."""
    match = re.search(r"\{.*\}", str(raw), re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the reply")
    data = json.loads(match.group(0))
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    confidence = float(data.get("confidence", 0.0))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence outside [0, 1]")
    return {"verdict": verdict, "confidence": confidence, "category": str(data.get("category", ""))[:60],
            "reason": str(data.get("reason", ""))[:240]}


class Layer3Judge:
    def __init__(self, provider: Optional[LLMProvider] = None, daily_calls: int = 500, min_confidence: float = 0.7,
                 downgrade_to: str = "REVIEW", cache_size: int = 512,
                 max_tokens: int = 200, deterministic_marker: bool = False, clock=time.time):
        if downgrade_to not in ("REVIEW", "ALLOW"):
            raise ValueError("downgrade_to must be REVIEW or ALLOW")
        self.provider = provider
        self.min_confidence = min_confidence
        self.downgrade_to = downgrade_to
        self.max_tokens = max_tokens
        self.deterministic_marker = deterministic_marker      # offline evaluation: same text, same prompt
        self.budget = DailyBudget(daily_calls, clock=clock)
        self._cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        with open(PROMPT_PATH, "r", encoding="utf-8") as handle:
            self._template = handle.read()
        self.calls = 0

    # ------------------------------------------------------------------
    def build_prompt(self, text: str, source: str = "user") -> str:
        nonce = (hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12] if self.deterministic_marker
                 else secrets.token_hex(6)).upper()
        marker = "=====" + nonce + "====="
        return self._template.format(marker=marker, source=SOURCE_TEXT.get(source, SOURCE_TEXT["user"]),
                                     text=str(text)[:MAX_TEXT_CHARS])

    def judge(self, text: str, source: str = "user") -> Dict[str, Any]:
        """Ask the provider. Returns {"ok": True, verdict, ...} or {"ok": False, "error": "..."}."""
        if self.provider is None:
            return {"ok": False, "error": "no_provider"}
        key = hashlib.sha256(f"{source}\n{text}".encode("utf-8")).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return dict(self._cache[key], cached=True)
        if not self.budget.take():
            return {"ok": False, "error": "daily_budget_exhausted"}
        self.calls += 1
        try:
            reply = self.provider.complete(self.build_prompt(text, source), max_tokens=self.max_tokens, temperature=0.0)
            verdict = parse_verdict(reply)
        except ManualPending:
            return {"ok": False, "error": "manual_pending"}
        except LLMError as exc:
            return {"ok": False, "error": f"provider_error:{str(exc)[:120]}"}
        except (ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "error": f"bad_reply:{str(exc)[:120]}"}
        result = {"ok": True, **verdict}
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return dict(result, cached=False)

    # ------------------------------------------------------------------
    def resolve(self, side: str, verdict: Dict[str, Any]) -> Dict[str, Any]:
        """Combine the judge's answer with the side Layer 2 was unsure on. Returns {decision, reason, degraded}."""
        if not verdict.get("ok"):
            decision = "REVIEW" if side == "allow" else "BLOCK"
            return {"decision": decision, "degraded": True, "reason": f"layer3_unavailable:{verdict.get('error')}"}
        said, confident = verdict["verdict"], verdict["confidence"] >= self.min_confidence
        tag = f"layer3_{said}:{verdict['confidence']:.2f}"
        if said == "attack" and confident:
            return {"decision": "BLOCK", "degraded": False, "reason": tag}
        if said == "benign" and confident:
            return {"decision": "ALLOW" if side == "allow" else self.downgrade_to, "degraded": False, "reason": tag}
        return {"decision": "REVIEW" if side == "allow" else "BLOCK", "degraded": False, "reason": tag + ":not_confident"}

    def check(self, text: str, side: str = "allow", source: str = "user", l2_score: Optional[float] = None) -> Dict[str, Any]:
        started = time.perf_counter()
        verdict = self.judge(text, source)
        outcome = self.resolve(side, verdict)
        details = {"side": side, "source": source, "prompt_version": PROMPT_VERSION, "l2_score": l2_score,
                   "provider": getattr(self.provider, "name", None), "cached": verdict.get("cached", False)}
        details.update({k: verdict[k] for k in ("verdict", "confidence", "category", "reason") if k in verdict})
        if not verdict.get("ok"):
            details["error"] = verdict.get("error")
        return {"layer": 3, "decision": outcome["decision"], "degraded": outcome["degraded"],
                "confidence": verdict.get("confidence", 0.0), "reason": outcome["reason"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2), "details": details}

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self.provider is not None


def build_judge_from_env() -> Optional[Layer3Judge]:
    """
    Layer 3 from the environment. FIREWALL_JUDGE_PROVIDER = gemini | ollama | anthropic | openai | none (default
    none: no judge, Layer 2 decides alone). A provider that cannot start (missing key) disables the judge, with the
    reason kept in `build_judge_error`, instead of crashing the API.
    """
    from firewall.llm_provider import get_provider, load_env_file

    load_env_file()          # .env is git-ignored; variables already in the environment win
    name = os.environ.get("FIREWALL_JUDGE_PROVIDER", "").strip().lower()
    if name in ("", "none"):
        return None
    try:
        provider = get_provider(name)
    except LLMError as exc:
        build_judge_from_env.error = str(exc)
        return None
    # The judge sits in the request path: a slow provider must not hold the user for half a minute.
    if hasattr(provider, "timeout"):
        provider.timeout = min(float(provider.timeout), JUDGE_TIMEOUT_SECONDS)
    if hasattr(provider, "retries"):
        provider.retries = 0
    return Layer3Judge(provider, daily_calls=int(os.environ.get("FIREWALL_JUDGE_DAILY_CALLS", "500")))


build_judge_from_env.error = None
