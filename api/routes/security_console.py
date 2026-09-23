"""
Security Console Route: Powers the SOC Incident Monitoring Dashboard.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Query
from api.incident_store import incident_store
from api.schemas import IncidentLogItem

router = APIRouter()

@router.get("/incidents", response_model=List[IncidentLogItem])
def get_incidents(limit: int = Query(50, ge=1, le=200)):
    """Fetch latest threat incident events."""
    return incident_store.get_incidents(limit=limit)

@router.get("/stats")
def get_stats() -> Dict[str, Any]:
    """Fetch aggregate security statistics."""
    return incident_store.get_stats()

@router.post("/clear")
def clear_incidents():
    """Clear incident log for clean demo runs."""
    incident_store.incidents.clear()
    incident_store._save()
    return {"status": "cleared"}
