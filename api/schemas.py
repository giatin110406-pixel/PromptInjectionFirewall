"""
Pydantic Schemas for AI Firewall API.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, description="User prompt to inspect")
    session_id: Optional[str] = "session_default"
    user_id: Optional[str] = "user_anon"

class AuthUser(BaseModel):
    user_id: str
    username: str
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser

class LayerTraceItem(BaseModel):
    layer: int
    decision: str
    reason: Optional[str] = None
    confidence: Optional[float] = None
    latency_ms: Optional[float] = None
    matched_pattern: Optional[str] = None

class ChatResponse(BaseModel):
    status: str = Field(..., description="'allowed', 'sanitized', 'review' or 'blocked'")
    decision: str = Field(..., description="ALLOW, SANITIZE, REVIEW or BLOCK")
    stopped_at_layer: int
    final_reason: str
    total_latency_ms: float
    trace: List[Dict[str, Any]]
    agent_reply: Optional[str] = None

class ActionRequest(BaseModel):
    action_type: str = Field(..., description="e.g. 'refund', 'data_access'")
    payload: Dict[str, Any]

class ActionResponse(BaseModel):
    layer: int = 4
    decision: str
    reason: Optional[str] = None
    latency_ms: float
    validated_data: Optional[Dict[str, Any]] = None

class IncidentLogItem(BaseModel):
    id: str
    timestamp: str
    session_id: str
    user_id: str
    input_text: str
    blocked_by_layer: int
    reason: str
    confidence: float
    total_latency_ms: float
    trace: List[Dict[str, Any]]
