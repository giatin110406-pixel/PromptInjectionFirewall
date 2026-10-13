"""
Security Console Route: Powers the SOC Incident Monitoring Dashboard.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query
from api.dependencies.auth import get_current_user
from api.incident_store import incident_store
from api.schemas import AuthUser, IncidentLogItem

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
    return incident_store.get_stats()

@router.post("/clear")
def clear_incidents(current_user: AuthUser = Depends(get_current_user)):
    """Clear incident log for clean demo runs."""
    if "security_admin" not in current_user.roles:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    incident_store.incidents.clear()
    incident_store._save()
    return {"status": "cleared"}
