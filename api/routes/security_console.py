"""
Security Console Route: Powers the SOC Incident Monitoring Dashboard.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query
from api.dependencies.auth import get_current_user
from api.feedback_store import KINDS, feedback_store
from api.incident_store import incident_store
from api.schemas import AuthUser, FeedbackIn, IncidentLogItem

router = APIRouter()

@router.get("/incidents", response_model=List[IncidentLogItem])
def get_incidents(limit: int = Query(50, ge=1, le=200), current_user: AuthUser = Depends(get_current_user)):
    """Fetch latest threat incident events."""
    if "security_admin" not in current_user.roles and "chat:read" not in current_user.permissions:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    return incident_store.get_incidents(limit=limit)

@router.get("/stats")
def get_stats(current_user: AuthUser = Depends(get_current_user)) -> Dict[str, Any]:
    """Fetch aggregate security statistics."""
    if "security_admin" not in current_user.roles:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    stats = incident_store.get_stats()
    from api.routes import chat as chat_routes

    engine = chat_routes.orchestrator
    stats["pending_reviews"] = len(engine.review_queue.list("pending"))
    stats["tainted_sessions"] = len(engine.taint.tainted_sessions())
    stats["feedback"] = feedback_store.counts()
    return stats


def _require_admin(user: AuthUser) -> None:
    if "security_admin" not in user.roles:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")


@router.post("/feedback")
def add_feedback(item: FeedbackIn, current_user: AuthUser = Depends(get_current_user)) -> Dict[str, Any]:
    """Record that a decision was wrong. It is training data and a regression case, never an automatic allow-list."""
    _require_admin(current_user)
    if item.kind not in KINDS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"kind must be one of {KINDS}")
    return feedback_store.add(item.kind, item.text, mode=item.mode, decision=item.decision, layer=item.layer,
                              reason=item.reason, note=item.note, user=current_user.username, session_id=item.session_id)


@router.get("/feedback")
def list_feedback(limit: int = Query(50, ge=1, le=500), kind: str = None,
                  current_user: AuthUser = Depends(get_current_user)) -> List[Dict[str, Any]]:
    _require_admin(current_user)
    return feedback_store.list(limit=limit, kind=kind)


@router.get("/sessions")
def get_tainted_sessions(current_user: AuthUser = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Sessions currently marked TAINT (untrusted content carried an instruction), with the events that tainted them."""
    if "security_admin" not in current_user.roles:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    from api.routes import chat as chat_routes

    engine = chat_routes.orchestrator
    return [dict(engine.taint.info(sid), session_id=sid) for sid in engine.taint.tainted_sessions()]


@router.get("/health")
def get_engine_health(current_user: AuthUser = Depends(get_current_user)) -> Dict[str, Any]:
    """Per-layer readiness for the console (same data as /health, behind the console login)."""
    from api.routes import chat as chat_routes

    health = chat_routes.orchestrator.health()
    judge = chat_routes.orchestrator.layer3
    health["demo_mode"] = chat_routes.demo_mode()
    health["judge"] = {
        "configured": getattr(judge, "provider", None) is not None,
        "provider": getattr(getattr(judge, "provider", None), "name", None),
        "calls_today": getattr(getattr(judge, "budget", None), "used", None),
        "daily_cap": getattr(getattr(judge, "budget", None), "limit", None),
        "used_only_when_requested": True,
    }
    return health

@router.post("/clear")
def clear_incidents(current_user: AuthUser = Depends(get_current_user)):
    """Clear incident log for clean demo runs."""
    if "security_admin" not in current_user.roles:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    incident_store.incidents.clear()
    incident_store._save()
    return {"status": "cleared"}
