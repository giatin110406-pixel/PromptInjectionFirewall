"""
The agent loop with the firewall in the middle (docs/agent_plan_vi.md section 3).

    customer text -> process_input -> LLM -> tool call
        read tool   -> backend text -> process_context -> (datamarked) text back to the LLM
        action tool -> validate_action -> ALLOW: _execute | REVIEW: wait for confirm() | BLOCK: tell the LLM, do nothing

Modes: "off" (no firewall call: the baseline), "detection" (Layer 4 reacts only to a flagged instruction) and
"provenance" (Layer 4 also reacts to unflagged untrusted content), passed per validation call.
Every state change of the backend goes through `Agent._execute`, which runs only after the
firewall said ALLOW (or no firewall is configured), or after a confirmation.
"""
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Dict, List, Optional

from agent.backend import DOMAINS, MockBackend
from agent.llm import AgentLLMError, CallBudgetExceeded, QuotaExhausted, ToolLLM
from agent.prompts import system_prompt
from agent.progress import ProgressTracker
from agent.tools import TOOLS, build_payload, check_arguments, openai_tools
from firewall.deadline import DeadlineExceeded, check_deadline, deadline_lock, turn_deadline
from firewall.progress import emit_progress, observe_progress, progress_phase

MODES = ("off", "detection", "provenance")
DEFAULT_MAX_STEPS = 6
_ENGINE_LOCK = threading.Lock()         # serialize context inference on the shared model


def _serial_session(method):
    """A reset, chat, poll or confirmation cannot race another write to the same backend."""
    @wraps(method)
    def locked(self, session_id, *args, **kwargs):
        lock = self._session_locks.setdefault(session_id, threading.RLock())
        if not lock.acquire(timeout=2.0):
            raise SessionBusyError("Phiên đang xử lý yêu cầu trước. Vui lòng chờ trước khi gửi tiếp.")
        try:
            return method(self, session_id, *args, **kwargs)
        finally:
            lock.release()
    return locked


class ReviewNotFound(KeyError):
    """The review id is not pending in this session."""


class SessionBusyError(RuntimeError):
    pass


@dataclass
class AgentSession:
    domain: str
    backend: MockBackend
    messages: List[Dict[str, Any]]
    lang: str = "vi"
    pending: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    progress: ProgressTracker = field(default_factory=ProgressTracker)


@dataclass
class AgentResult:
    session_id: str
    mode: str
    reply: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    pending_review: Optional[Dict[str, Any]] = None
    stopped: Optional[str] = None            # input_block, input_review, max_steps, llm_error
    error: Optional[str] = None
    error_code: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    fatal: bool = False                      # budget or quota exhausted: the caller should stop its run
    attempts: List[Dict[str, Any]] = field(default_factory=list)       # every action tool call the LLM made, before any check
    executed: List[Dict[str, Any]] = field(default_factory=list)       # actions the backend carried out during this run
    llm_calls: int = 0
    latency_ms: float = 0.0
    backend_state: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, Any] = field(default_factory=dict)
    provider: Optional[str] = None
    model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _describe(action: str, p: Dict[str, Any]) -> str:
    if action in ("transfer_money", "transfer"):
        return f"chuyển {float(p.get('amount', 0)):,.0f} {p.get('currency', 'VND')} tới tài khoản {p.get('to_account')}"
    if action == "refund":
        return f"hoàn {p.get('amount')} USD cho đơn {p.get('order_id')}"
    if action == "data_access":
        return f"truy xuất \"{p.get('resource')}\" (phạm vi {p.get('query_scope', 'own_account')})"
    if action == "send_email":
        return "gửi email tới " + ", ".join(p.get("to") or [])
    return action


class Agent:
    def __init__(self, engine=None, llm: Optional[ToolLLM] = None, mode: str = "provenance", max_steps: Optional[int] = None):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.engine, self.llm, self.mode = engine, llm, mode
        self.max_steps = max_steps or int(os.environ.get("AGENT_MAX_STEPS", DEFAULT_MAX_STEPS))
        self.sessions: Dict[str, AgentSession] = {}
        self._session_locks = {}

    # ---------------------------------------------------------------- sessions
    @_serial_session
    def reset(self, session_id: str, domain: str = "bank", contents=(), identity: Optional[Dict[str, Any]] = None,
              lang: str = "vi") -> AgentSession:
        """A fresh backend and conversation. `contents`: (channel, text) pairs put where the read tools find them."""
        if domain not in DOMAINS:
            raise ValueError(f"domain must be one of {DOMAINS}")
        backend = MockBackend(domain, identity)
        for channel, text in contents:
            backend.load_content(channel, text)
        if self.engine is not None:               # same id again: forget what the firewall learned about the old session
            for store in (self.engine.taint, self.engine.values, self.engine.turn_risk):
                store.clear(session_id)
        system = system_prompt(domain, lang, backend.identity, backend.describe_resources())
        session = AgentSession(domain, backend, [{"role": "system", "content": system}], lang)
        self.sessions[session_id] = session
        return session

    def session(self, session_id: str) -> AgentSession:
        if session_id not in self.sessions:
            raise KeyError(f"unknown agent session '{session_id}': call reset first")
        return self.sessions[session_id]

    def progress(self, session_id: str, after: int = 0) -> Dict[str, Any]:
        return self.session(session_id).progress.snapshot(after)

    @_serial_session
    def state(self, session_id: str) -> Dict[str, Any]:
        session = self.session(session_id)
        self.sync(session_id)
        return {"domain": session.domain, "backend_state": session.backend.snapshot(),
                "pending": [dict(v, review_id=k) for k, v in session.pending.items()]}

    # ---------------------------------------------------------------- one customer message
    @_serial_session
    def run(self, session_id: str, user_text: str, llm: Optional[ToolLLM] = None, mode: Optional[str] = None) -> AgentResult:
        session, llm, mode = self.session(session_id), llm or self.llm, mode or self.mode
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if llm is None:
            raise ValueError("no LLM configured")
        result = AgentResult(session_id=session_id, mode=mode)
        result.provider, result.model = getattr(llm, "name", None), getattr(llm, "model", None)
        session.progress.start(user_text)
        started, calls_before = time.perf_counter(), llm.calls
        try:
            with turn_deadline(float(os.environ.get("AGENT_TURN_TIMEOUT_SECONDS", "35"))), observe_progress(session.progress.emit):
                self._run(session, session_id, user_text, llm, mode, result)
        except DeadlineExceeded:
            result.error = "Agent turn timed out"
            result.error_code, result.stopped = "timeout", "timeout"
            result.reply = "Yêu cầu xử lý quá lâu và đã dừng. Hãy kiểm tra trạng thái tác vụ trước khi gửi lại."
        except AgentLLMError as exc:
            result.error, result.stopped = str(exc), "llm_error"
            result.fatal = isinstance(exc, (CallBudgetExceeded, QuotaExhausted))
            result.error_code = "rate_limit" if isinstance(exc, QuotaExhausted) else "provider_error"
            if isinstance(exc, QuotaExhausted):
                wait = getattr(exc, "retry_in", None)
                result.retry_after_seconds = max(1, math.ceil(wait)) if wait is not None else None
                retry = f" khoảng {result.retry_after_seconds} giây" if result.retry_after_seconds else " một lúc"
                result.reply = f"Power Agent đang chạm giới hạn sử dụng của {llm.name}. Yêu cầu chưa hoàn tất; hãy thử lại sau{retry}."
            else:
                result.reply = "Dịch vụ LLM tạm thời không hoàn tất được yêu cầu. Hãy kiểm tra trạng thái tác vụ trước khi thử lại."
            result.steps.append({"kind": "llm_error", "error": str(exc)})
        except Exception:
            session.progress.finish("ERROR", "Yêu cầu không hoàn tất")
            raise
        finally:
            action_decision = next((s.get("decision") for s in reversed(result.steps)
                                    if s.get("kind") == "tool_action"), None)
            input_decision = next((s.get("decision") for s in result.steps
                                   if s.get("kind") == "firewall_input"), "ALLOW")
            final = ("ERROR" if result.error else "REVIEW" if result.pending_review else
                     "STOPPED" if result.stopped else action_decision or input_decision)
            session.progress.finish(final, result.reply if result.error else None,
                                    result.error_code if result.error else None)
        if result.error:
            # Close outstanding tool-call protocol entries before another user turn.
            for i in range(len(session.messages) - 1, -1, -1):
                message = session.messages[i]
                if message.get("role") == "assistant" and message.get("tool_calls"):
                    answered = {m.get("tool_call_id") for m in session.messages[i + 1:] if m.get("role") == "tool"}
                    for call in message["tool_calls"]:
                        if call["id"] not in answered:
                            session.messages.append({"role": "tool", "tool_call_id": call["id"],
                                                     "content": json.dumps({"error": "Turn stopped before this tool completed"})})
                    break
                if message.get("role") == "user":
                    break
            session.messages.append({"role": "assistant", "content": result.reply})
        result.llm_calls = llm.calls - calls_before
        result.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        result.backend_state = session.backend.snapshot()
        result.progress = session.progress.snapshot()
        return result

    def _run(self, session, sid, user_text, llm, mode, result) -> None:
        if mode != "off":
            with progress_phase("input"):
                r = self.engine.process_input(user_text, source="user", use_judge=getattr(self.engine, "auto_judge", False), session_id=sid)
            check_deadline()
            result.steps.append({"kind": "firewall_input", "decision": r["decision"], "layer": r["stopped_at_layer"],
                                 "reason": r["final_reason"], "ms": r["total_latency_ms"], "trace": r["trace"],
                                 "judge": r.get("judge_adjudication")})
            if r["decision"] in ("BLOCK", "REVIEW"):
                result.stopped = "input_block" if r["decision"] == "BLOCK" else "input_review"
                result.reply = ("Tin nhắn bị chặn trước khi tới trợ lý." if r["decision"] == "BLOCK"
                                else "Tin nhắn đang được giữ lại để kiểm tra; trợ lý chưa nhận được.")
                return
        session.messages.append({"role": "user", "content": user_text})
        tools = openai_tools()
        for _ in range(self.max_steps):
            check_deadline()
            t = time.perf_counter()
            emit_progress(stage="AGENT", phase="agent", state="running", provider=llm.name, model=getattr(llm, "model", None))
            turn = llm.chat(session.messages, tools)
            check_deadline()
            result.steps.append({"kind": "llm", "text": turn.text, "tool_calls": [c.name for c in turn.tool_calls],
                                 "ms": round((time.perf_counter() - t) * 1000, 1)})
            emit_progress(stage="AGENT", phase="agent", state="done", decision="TOOL_CALL" if turn.tool_calls else "REPLY",
                          tools=[c.name for c in turn.tool_calls], preview=turn.text[:200],
                          latency_ms=round((time.perf_counter() - t) * 1000, 1))
            session.messages.append(turn.to_message())
            if not turn.tool_calls:
                result.reply = turn.text
                return
            waiting = False
            for call in turn.tool_calls:
                if waiting:
                    content = {"error": "chưa thực hiện: đang chờ khách xác nhận lệnh trước"}
                else:
                    content, waiting = self._call(session, sid, call, mode, result)
                session.messages.append({"role": "tool", "tool_call_id": call.id, "content": content if isinstance(content, str)
                                         else json.dumps(content, ensure_ascii=False)})
            if waiting:
                review = result.pending_review
                result.reply = f"Lệnh {_describe(review['action'], review['payload'])} đang chờ xác nhận ({review['review_by']})."
                return
        result.stopped = "max_steps"
        result.reply = "Đã đạt giới hạn số bước của trợ lý."

    # ---------------------------------------------------------------- one tool call: returns (content, waiting)
    def _call(self, session, sid, call, mode, result):
        spec = TOOLS.get(call.name)
        if spec is not None and spec.kind == "action":
            result.attempts.append({"tool": call.name, "arguments": call.arguments})
        if call.parse_error or spec is None:
            error = call.parse_error or f"unknown tool '{call.name}'"
            result.steps.append({"kind": "agent_error", "tool": call.name, "error": error})
            return {"error": error}, False
        args, error = check_arguments(call.name, call.arguments)
        if error:
            result.steps.append({"kind": "agent_error", "tool": call.name, "error": error})
            return {"error": error}, False
        if spec.kind == "read":
            return self._read(session, sid, call, args, mode, result), False
        return self._action(session, sid, call, args, mode, result)

    def _read(self, session, sid, call, args, mode, result) -> str:
        text = session.backend.read(call.name, args)
        step = {"kind": "tool_read", "tool": call.name, "arguments": args, "chars": len(text)}
        if mode == "off":
            step["firewall"] = None
            result.steps.append(step)
            return text
        spec = TOOLS[call.name]
        with deadline_lock(_ENGINE_LOCK), progress_phase("context", tool=call.name):
            ctx = self.engine.process_context([{"id": f"{call.id}", "text": text, "source": spec.source}], session_id=sid,
                                              use_judge=getattr(self.engine, "auto_judge", False))
        step["firewall"] = {"decision": ctx["decision"], "tainted": ctx["tainted"], "session_level": ctx["session_level"],
                            "ms": ctx["total_latency_ms"],
                            "judge_checks": [check for chunk in ctx["chunks"] for check in chunk.get("judge_checks", [])]}
        result.steps.append(step)
        return ctx["sanitized_context"] or "[Nội dung bị firewall giữ lại, không đưa cho trợ lý]"

    def _action(self, session, sid, call, args, mode, result):
        payload = build_payload(call.name, args, session.backend.identity, session.backend)
        step = {"kind": "tool_action", "tool": call.name, "payload": payload}
        if mode == "off":
            step.update(decision="ALLOW", check="firewall_off")
            result.steps.append(step)
            return self._execute(session, call.name, payload, result), False
        emit_progress(stage="L4", phase="action", state="running", tool=call.name)
        with deadline_lock(_ENGINE_LOCK), progress_phase("action", tool=call.name):
            # Mode belongs to this call; never temporarily weaken the shared engine for other API requests.
            r = self.engine.validate_action(call.name, payload, session_id=sid, exposure_mode=mode)
        emit_progress(stage="L4", phase="action", state="done", tool=call.name, decision=r["decision"],
                      check=r.get("check"), reason=r.get("reason"), latency_ms=r.get("latency_ms"),
                      payload=payload, provenance=r.get("value_provenance", []))
        step.update(decision=r["decision"], check=r.get("check"), reason=r.get("reason"), session_level=r.get("session_level"),
                    review_id=r.get("review_id"), review_by=r.get("review_by"), ms=r.get("latency_ms"),
                    provenance=r.get("provenance"), value_provenance=r.get("value_provenance"))
        result.steps.append(step)
        if r["decision"] == "ALLOW":
            return self._execute(session, call.name, payload, result), False
        if r["decision"] == "BLOCK":
            return {"error": f"Firewall từ chối hành động và không thực hiện: {r.get('reason')}"}, False
        review = {"action": call.name, "payload": payload, "review_by": r.get("review_by"), "reason": r.get("reason"),
                  "provenance": r.get("provenance"), "value_provenance": r.get("value_provenance")}
        session.pending[r["review_id"]] = review
        result.pending_review = dict(review, review_id=r["review_id"])
        return {"status": "chờ khách xác nhận", "review_id": r["review_id"]}, True

    def _execute(self, session, action: str, payload: Dict[str, Any], result: Optional[AgentResult]) -> Dict[str, Any]:
        """The only place where the backend changes. Reached after ALLOW, a confirmation, or with the firewall off."""
        check_deadline()
        outcome = session.backend.apply(action, payload)
        if outcome["ok"] and result is not None:
            result.executed.append({"type": action, "payload": payload})
        return outcome

    # ---------------------------------------------------------------- confirmation of a held action
    @_serial_session
    def confirm(self, session_id: str, review_id: str, approve: bool) -> Dict[str, Any]:
        """Carry out or drop the action held under `review_id`. The review queue is the authority when it already holds
        a decision (a supervisor may have decided on the console). Only a review of this session is accepted."""
        session = self.session(session_id)
        pending = session.pending.get(review_id)
        if pending is None:
            raise ReviewNotFound(review_id)
        approved = bool(approve)
        queue = self.engine.review_queue if self.engine is not None else None
        item = queue.get(review_id) if queue is not None else None
        if item is not None:
            if item["status"] == "pending":
                queue.decide(review_id, approved, reviewer="customer", note="xác nhận trong chat với agent")
            else:
                approved = item["status"] == "approved"
        return self._resolve(session, review_id, approved)

    def _resolve(self, session, review_id: str, approved: bool) -> Dict[str, Any]:
        pending = session.pending.pop(review_id)
        if approved:
            outcome = self._execute(session, pending["action"], pending["payload"], None)
            message = outcome["message"]
            note = f"Khách đã xác nhận. {message}" if outcome["ok"] else f"Không thực hiện được: {message}"
        else:
            outcome, note = {"ok": False, "message": "đã hủy"}, "Khách đã hủy lệnh; không có gì được thực hiện."
        session.messages.append({"role": "assistant", "content": note})
        return {"review_id": review_id, "status": "approved" if approved else "rejected", "executed": bool(approved and outcome["ok"]),
                "message": note, "action": pending["action"], "backend_state": session.backend.snapshot()}

    @_serial_session
    def sync(self, session_id: str) -> List[Dict[str, Any]]:
        """Apply decisions made elsewhere (a supervisor on the console) to the held actions of this session."""
        session = self.session(session_id)
        if self.engine is None:
            return []
        done = []
        for review_id in list(session.pending):
            item = self.engine.review_queue.get(review_id)
            if item is not None and item["status"] in ("approved", "rejected"):
                done.append(self._resolve(session, review_id, item["status"] == "approved"))
        return done
