"""
Chat Route: Primary entry point for client conversational queries.
"""
from fastapi import APIRouter
from api.schemas import ChatRequest, ChatResponse, ActionRequest, ActionResponse
from api.incident_store import incident_store
from firewall.orchestrator import FirewallOrchestrator

router = APIRouter()
orchestrator = FirewallOrchestrator()

@router.post("/message", response_model=ChatResponse)
def process_message(req: ChatRequest):
    result = orchestrator.process_input(req.text)
    
    if result["decision"] == "BLOCK":
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
            user_id=req.user_id
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

    # Allowed: proceed to mock conversational agent response
    agent_reply = f"Thank you for contacting customer support. We received your query: '{req.text}'. How else may we assist you?"
    return ChatResponse(
        status="allowed",
        decision="ALLOW",
        stopped_at_layer=result["stopped_at_layer"],
        final_reason=result["final_reason"],
        total_latency_ms=result["total_latency_ms"],
        trace=result["trace"],
        agent_reply=agent_reply
    )

@router.post("/action", response_model=ActionResponse)
def process_action(req: ActionRequest):
    result = orchestrator.validate_action(req.action_type, req.payload)
    if result["decision"] == "BLOCK":
        incident_store.log_incident(
            input_text=f"Action: {req.action_type} - {req.payload}",
            blocked_by_layer=4,
            reason=result.get("reason", "policy_violation"),
            confidence=1.0,
            total_latency_ms=result["latency_ms"],
            trace=[result]
        )
    return ActionResponse(
        layer=4,
        decision=result["decision"],
        reason=result.get("reason"),
        latency_ms=result["latency_ms"],
        validated_data=result.get("validated_data")
    )
