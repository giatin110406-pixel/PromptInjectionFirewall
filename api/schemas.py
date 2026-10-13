"""
Pydantic Schemas for AI Firewall API.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class DebugOptions(BaseModel):
    """Manual-testing switches. Both need a security_admin; skipping layers also needs FIREWALL_DEMO_MODE=1."""
    skip_layers: List[str] = Field(default_factory=list, description="L1, L2, L3, clean, L4_hard, L4_taint, L4_policy, L5")
    use_judge: bool = Field(False, description="Let Layer 3 call the paid LLM judge for this request (default: no)")


class ChatRequest(DebugOptions):
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

class ContextChunkIn(BaseModel):
    id: str
    text: str
    source: str = Field("document", description="email, web, rag, tool or document")

class ContextRequest(DebugOptions):
    chunks: List[ContextChunkIn] = Field(..., min_length=1, description="Untrusted content to scan")
    session_id: Optional[str] = "session_default"
    user_id: Optional[str] = "user_anon"

class ContextResponse(BaseModel):
    decision: str = Field(..., description="ALLOW, SANITIZE or REVIEW (a context scan never blocks the user)")
    tainted: bool
    session_tainted: bool
    degraded: bool = False
    chunks: List[Dict[str, Any]]
    sanitized_context: str = Field("", description="Surviving text, delimited and datamarked, to place in the prompt")
    total_latency_ms: float

class OutputRequest(DebugOptions):
    text: str = Field(..., description="What the agent is about to send")
    session_id: Optional[str] = "session_default"
    allow_text: str = Field("", description="What the user wrote; its own data may be repeated back")
    protected_texts: List[str] = Field(default_factory=list, description="Texts that must not be echoed, e.g. the system prompt")

class OutputResponse(BaseModel):
    layer: int = 5
    decision: str = Field(..., description="ALLOW, SANITIZE or BLOCK")
    reason: str
    sanitized_text: str = Field("", description="Safe text to send; empty when BLOCK")
    findings: List[Dict[str, Any]]
    latency_ms: float

class ActionRequest(DebugOptions):
    action_type: str = Field(..., description="e.g. 'refund', 'data_access'")
    payload: Dict[str, Any]
    session_id: Optional[str] = Field(None, description="Links the action to earlier /chat/context scans (taint)")

class ActionResponse(BaseModel):
    layer: int = 4
    decision: str = Field(..., description="ALLOW, REVIEW or BLOCK")
    reason: Optional[str] = None
    latency_ms: float
    validated_data: Optional[Dict[str, Any]] = None
    tainted: bool = False
    review_id: Optional[str] = Field(None, description="Set when the action waits for a human decision")
    check: Optional[str] = Field(None, description="hard_rule, taint, policy, rate_limit or none")

class ReviewDecisionRequest(BaseModel):
    approve: bool
    note: Optional[str] = None

class FeedbackIn(BaseModel):
    kind: str = Field(..., description="false_positive (a block was wrong) or missed_attack (an attack got through)")
    text: str = Field(..., min_length=1)
    mode: str = "message"
    decision: str = ""
    layer: Optional[int] = None
    reason: str = ""
    note: str = ""
    session_id: str = ""

class IncidentLogItem(BaseModel):
    id: str
    timestamp: str
    session_id: str
    user_id: str
    input_text: str
    blocked_by_layer: int
    decision: str = "BLOCK"
    reason: str
    confidence: float
    total_latency_ms: float
    trace: List[Dict[str, Any]]
