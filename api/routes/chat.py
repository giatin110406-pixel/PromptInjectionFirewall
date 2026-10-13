"""
Chat Route: Primary entry point for client conversational queries.
"""
import os

from fastapi import APIRouter, Depends
from api.dependencies.auth import get_current_user
from api.schemas import (AuthUser, ChatRequest, ChatResponse, ActionRequest, ActionResponse,
                         ContextRequest, ContextResponse, ReviewDecisionRequest,
                         OutputRequest, OutputResponse)
from fastapi import HTTPException
from api.incident_store import incident_store
from firewall.orchestrator import FirewallOrchestrator

router = APIRouter()


def demo_mode() -> bool:
    """Layer switches are a testing aid, off unless the operator sets FIREWALL_DEMO_MODE=1."""
    return os.environ.get("FIREWALL_DEMO_MODE", "") == "1"


def debug_options(user: AuthUser, skip_layers, use_judge):
    """Validate the manual-testing switches of a request. Returns (skip_layers, use_judge)."""
    if not skip_layers and not use_judge:
        return [], False
    if "security_admin" not in {r.lower() for r in user.roles}:
        raise HTTPException(status_code=403, detail="Layer switches and the paid judge are for security_admin only")
    if skip_layers and not demo_mode():
        raise HTTPException(status_code=403, detail="Layer switches are off. Start the API with FIREWALL_DEMO_MODE=1")
    return list(skip_layers), bool(use_judge)
from firewall.judge import build_judge_from_env

orchestrator = FirewallOrchestrator(layer3=build_judge_from_env())

@router.post("/message", response_model=ChatResponse)
def process_message(req: ChatRequest, current_user: AuthUser = Depends(get_current_user)):
    skip, judge = debug_options(current_user, req.skip_layers, req.use_judge)
    result = orchestrator.process_input(req.text, skip=skip, use_judge=judge)
    
    if result["decision"] in ("BLOCK", "REVIEW"):
        last_step = result["trace"][-1] if result["trace"] else {}
        conf = last_step.get("confidence", 1.0)
        
        # Log attack to Security Console
        incident_store.log_incident(
            input_text=req.text,
            blocked_by_layer=result["stopped_at_layer"],
            reason=result["final_reason"],
            confidence=conf,
            total_latency_ms=result["total_latency_ms"],
            trace=result["trace"],
            session_id=req.session_id,
            user_id=req.user_id,
            decision=result["decision"],
        )

        if result["decision"] == "REVIEW":
            return ChatResponse(
                status="review",
                decision="REVIEW",
                stopped_at_layer=result["stopped_at_layer"],
                final_reason=result["final_reason"],
                total_latency_ms=result["total_latency_ms"],
                trace=result["trace"],
                agent_reply="[FIREWALL REVIEW] Yêu cầu của bạn đang được giữ lại để kiểm tra thêm. Bạn có thể diễn đạt lại rõ hơn hoặc chờ nhân viên duyệt. / Your request is held for review: please rephrase it or wait for a human to check it."
            )

        return ChatResponse(
            status="blocked",
            decision="BLOCK",
            stopped_at_layer=result["stopped_at_layer"],
            final_reason=result["final_reason"],
            total_latency_ms=result["total_latency_ms"],
            trace=result["trace"],
            agent_reply="[FIREWALL BLOCKED] Your request violated security policy and was intercepted."
        )

    # Allowed: proceed to mock conversational agent response, then check it with Layer 5
    agent_reply = f"Thank you for contacting customer support. We received your query: '{req.text}'. How else may we assist you?"
    guarded = _guard_output(agent_reply, req.session_id, req.text, req.user_id)
    agent_reply = guarded if guarded is not None else "[FIREWALL BLOCKED] The reply was withheld because it would have exposed protected data."
    return ChatResponse(
        status="allowed" if result["decision"] == "ALLOW" else "sanitized",
        decision=result["decision"],
        stopped_at_layer=result["stopped_at_layer"],
        final_reason=result["final_reason"],
        total_latency_ms=result["total_latency_ms"],
        trace=result["trace"],
        agent_reply=agent_reply
    )

def _guard_output(text: str, session_id: str, allow_text: str, user_id: str):
    """Layer 5 on an agent reply. Returns the safe text, or None when the reply must be withheld."""
    out = orchestrator.check_output(text, session_id=session_id, allow_text=allow_text)
    if out["decision"] != "ALLOW":
        incident_store.log_incident(
            input_text=f"[output] {text}"[:2000], blocked_by_layer=5, reason=out["reason"], confidence=1.0,
            total_latency_ms=out["latency_ms"], trace=[out], session_id=session_id or "session_default", user_id=user_id,
            decision=out["decision"])
    return None if out["decision"] == "BLOCK" else out["sanitized_text"]


@router.post("/output", response_model=OutputResponse)
def check_output(req: OutputRequest, current_user: AuthUser = Depends(get_current_user)):
    """Layer 5: check an answer before it is shown to the user or passed to a tool."""
    skip, _ = debug_options(current_user, req.skip_layers, False)
    out = orchestrator.check_output(req.text, session_id=req.session_id, allow_text=req.allow_text,
                                    protected_texts=req.protected_texts, skip=skip)
    if out["decision"] != "ALLOW":
        incident_store.log_incident(
            input_text=f"[output] {req.text}"[:2000], blocked_by_layer=5, reason=out["reason"], confidence=1.0,
            total_latency_ms=out["latency_ms"], trace=[out], session_id=req.session_id or "session_default",
            user_id=current_user.user_id, decision=out["decision"])
    return OutputResponse(decision=out["decision"], reason=out["reason"], sanitized_text=out["sanitized_text"],
                          findings=out["findings"], latency_ms=out["latency_ms"])


@router.post("/context", response_model=ContextResponse)
def process_context(req: ContextRequest, current_user: AuthUser = Depends(get_current_user)):
    """Scan untrusted content (email, web, RAG, tool output) before it is given to the agent."""
    skip, judge = debug_options(current_user, req.skip_layers, req.use_judge)
    result = orchestrator.process_context([c.model_dump() for c in req.chunks], session_id=req.session_id,
                                          skip=skip, use_judge=judge)
    for entry in result["chunks"]:
        if entry["suspicious"]:
            incident_store.log_incident(
                input_text=f"[context:{entry['source']}:{entry['id']}] " + next(
                    (c.text for c in req.chunks if c.id == entry["id"]), "")[:2000],
                blocked_by_layer=entry["stopped_at_layer"], reason=entry["reason"], confidence=1.0,
                total_latency_ms=result["total_latency_ms"], trace=[entry],
                session_id=req.session_id, user_id=req.user_id, decision="SANITIZE")
    return ContextResponse(
        decision=result["decision"], tainted=result["tainted"], session_tainted=result["session_tainted"],
        degraded=result["degraded"], chunks=result["chunks"], sanitized_context=result["sanitized_context"],
        total_latency_ms=result["total_latency_ms"])


@router.post("/action", response_model=ActionResponse)
def process_action(req: ActionRequest, current_user: AuthUser = Depends(get_current_user)):
    skip, _ = debug_options(current_user, req.skip_layers, False)
    result = orchestrator.validate_action(req.action_type, req.payload, user=current_user, session_id=req.session_id, skip=skip)
    if result["decision"] in ("BLOCK", "REVIEW"):
        incident_store.log_incident(
            input_text=f"Action: {req.action_type} - {req.payload}",
            blocked_by_layer=4,
            reason=result.get("reason", "policy_violation"),
            confidence=1.0,
            total_latency_ms=result["latency_ms"],
            trace=[result],
            session_id=req.session_id or "session_default",
            user_id=current_user.user_id,
            decision=result["decision"],
        )
    return ActionResponse(
        layer=4,
        decision=result["decision"],
        reason=result.get("reason"),
        latency_ms=result["latency_ms"],
        validated_data=result.get("validated_data"),
        tainted=result.get("tainted", False),
        review_id=result.get("review_id"),
        check=result.get("check"),
    )


REVIEWER_ROLES = {"supervisor", "finance_lead", "security_admin", "admin"}


@router.get("/review")
def list_review(status: str = "pending", current_user: AuthUser = Depends(get_current_user)):
    """Actions waiting for a human decision. `status` is pending, approved, rejected or all."""
    return orchestrator.review_queue.list(None if status == "all" else status)


@router.post("/review/{item_id}/decision")
def decide_review(item_id: str, req: ReviewDecisionRequest, current_user: AuthUser = Depends(get_current_user)):
    if not REVIEWER_ROLES & {r.lower() for r in current_user.roles}:
        raise HTTPException(status_code=403, detail="Only supervisors, finance leads or security admins can decide")
    item = orchestrator.review_queue.decide(item_id, req.approve, reviewer=current_user.username, note=req.note)
    if item is None:
        raise HTTPException(status_code=404, detail="No pending review item with that id")
    return item
