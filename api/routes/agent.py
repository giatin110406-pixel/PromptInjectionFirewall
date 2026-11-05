"""
Agent route: a tool-calling agent running behind the firewall (agent/loop.py, docs/agent_plan_vi.md).
It shares the engine of api/routes/chat.py, so the console, /chat/review and this agent see the same sessions and review queue.
"""
import json
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from agent.backend import DOMAINS
from agent.attachments import AttachmentError, MAX_BYTES, fetch_attachment, parse_attachment
from agent.llm import AgentLLMError, ToolLLM, get_tool_llm
from agent.loop import MODES, Agent, ReviewNotFound
from api.dependencies.auth import get_current_user
from api.incident_store import incident_store
from api.routes import chat
from api.schemas import AuthUser

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENARIO_FILE = os.path.join(BASE_DIR, "frontend", "security-console", "lib", "demo_scenarios.json")
MAX_CONTENT_CHARS = 20_000

agent = Agent(engine=chat.orchestrator, mode="provenance")
_owners: Dict[str, str] = {}              # session id -> user id: one user cannot drive another's agent session
_OWNER_LOCK = threading.RLock()
_llms: Dict[str, ToolLLM] = {}            # one client per (provider, model), so AGENT_MAX_CALLS counts across requests


def weaker_modes_allowed() -> bool:
    """`off` and `detection` exist to show the demo audience what happens without the v4 firewall. They let a request
    bypass Layer 4, so they are refused unless the operator starts the API with AGENT_ALLOW_FIREWALL_OFF=1 (run_demo.bat)."""
    return os.environ.get("AGENT_ALLOW_FIREWALL_OFF", "") == "1"


class ContentIn(BaseModel):
    channel: str = Field("document", pattern="^(email|web|document|review|tool_json)$")
    text: str = Field(..., max_length=MAX_CONTENT_CHARS)


class AgentChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    text: str = Field(..., min_length=1, max_length=4000)
    domain: str = "bank"
    mode: str = "provenance"                # off | detection | provenance
    provider: Optional[str] = None          # scripted | groq | gemini | local; default AGENT_PROVIDER, then scripted
    lang: str = "vi"


class AgentConfirmRequest(BaseModel):
    session_id: str
    review_id: str
    approve: bool


class AgentResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    domain: str = "bank"
    scenario_id: Optional[str] = None       # a case id of lib/demo_scenarios.json: its document is put in the inbox / document store
    contents: List[ContentIn] = Field(default_factory=list)
    lang: str = "vi"


class AttachmentTextRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    domain: str = 'bank'
    channel: str = Field('document', pattern='^(email|web|document|review|tool_json)$')
    text: str = Field(..., min_length=1, max_length=MAX_CONTENT_CHARS)
    name: str = Field('Nội dung dán', min_length=1, max_length=160)


class AttachmentLinkRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=100)
    domain: str = 'bank'
    url: str = Field(..., min_length=1, max_length=2048)


def _attachment_access(session_id, domain, user):
    _check_domain(domain)
    with _OWNER_LOCK:
        _own(session_id, user)
        if session_id in agent.sessions and agent.session(session_id).domain != domain:
            raise HTTPException(status_code=409, detail='Bối cảnh khác phiên hiện tại; hãy tạo phiên mới.')


def _store_attachments(session_id, domain, user, items):
    with _OWNER_LOCK:
        _attachment_access(session_id, domain, user)
        if session_id not in agent.sessions:
            agent.reset(session_id, domain, identity={'user_id': user.user_id})
            _owners[session_id] = user.user_id
        try:
            return agent.attach(session_id, items)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))


@router.post('/attachments/upload')
def upload_attachments(session_id: str = Form(..., min_length=1, max_length=100),
                       domain: str = Form('bank'), files: List[UploadFile] = File(...),
                       current_user: AuthUser = Depends(get_current_user)):
    _attachment_access(session_id, domain, current_user)
    try:
        if not 1 <= len(files) <= 5:
            raise AttachmentError('Mỗi lần tải từ 1 đến 5 file.')
        items, total = [], 0
        for upload in files:
            data = upload.file.read(MAX_BYTES + 1)
            total += len(data)
            if total > 10 * 1024 * 1024:
                raise AttachmentError('Tổng file mỗi lần tải tối đa 10 MB.')
            items.append(parse_attachment(upload.filename, data))
        return _store_attachments(session_id, domain, current_user, items)
    except AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        for upload in files:
            upload.file.close()


@router.post('/attachments/link')
def attach_link(req: AttachmentLinkRequest, current_user: AuthUser = Depends(get_current_user)):
    _attachment_access(req.session_id, req.domain, current_user)
    try:
        item = fetch_attachment(req.url)
        return _store_attachments(req.session_id, req.domain, current_user, [item])
    except AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post('/attachments/text')
def attach_text(req: AttachmentTextRequest, current_user: AuthUser = Depends(get_current_user)):
    _attachment_access(req.session_id, req.domain, current_user)
    try:
        item = parse_attachment('text.txt', req.text.encode('utf-8'), source='paste')
        item.update(name=req.name, channel='document' if req.channel == 'review' else req.channel)
        return _store_attachments(req.session_id, req.domain, current_user, [item])
    except AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get('/attachments/{session_id}/{resource_id}')
def inspect_attachment(session_id: str, resource_id: str, current_user: AuthUser = Depends(get_current_user)):
    _own(session_id, current_user)
    if session_id not in agent.sessions:
        raise HTTPException(status_code=404, detail='Unknown agent session')
    try:
        return agent.attachment_text(session_id, resource_id)
    except KeyError:
        raise HTTPException(status_code=404, detail='Unknown attachment')


def _llm(provider: Optional[str], domain: str) -> ToolLLM:
    name = (provider or os.environ.get("AGENT_PROVIDER") or "scripted").lower()
    key = f"{name}:{domain if name == 'scripted' else ''}:{os.environ.get('AGENT_MODEL', '')}"
    if key not in _llms:
        try:
            _llms[key] = get_tool_llm(name, domain=domain, interactive=True)
        except AgentLLMError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    return _llms[key]


def _own(session_id: str, user: AuthUser) -> None:
    with _OWNER_LOCK:
        owner = _owners.get(session_id)
        if owner is not None and owner != user.user_id:
            raise HTTPException(status_code=403, detail="This agent session belongs to another user")


def _scenario_contents(scenario_id: str) -> List[tuple]:
    with open(SCENARIO_FILE, encoding="utf-8") as handle:
        data = json.load(handle)
    for conf in data["domains"].values():
        for case in conf["cases"]:
            if case["id"] == scenario_id:
                doc = case.get("doc")
                return [(doc["source"], doc["text"])] if doc else []
    raise HTTPException(status_code=404, detail=f"Unknown scenario '{scenario_id}'")


def _check_domain(domain: str) -> None:
    if domain not in DOMAINS:
        raise HTTPException(status_code=422, detail=f"domain must be one of {list(DOMAINS)}")


def _log(result: Dict[str, Any], text: str, session_id: str, user: AuthUser) -> None:
    for step in result["steps"]:
        held = (step["kind"] == "firewall_input" and step["decision"] in ("BLOCK", "REVIEW")) or \
               (step["kind"] == "tool_action" and step.get("decision") in ("BLOCK", "REVIEW"))
        if held:
            what = text if step["kind"] == "firewall_input" else f"Agent action: {step['tool']} - {step['payload']}"
            incident_store.log_incident(
                input_text=what[:2000], blocked_by_layer=step.get("layer", 4), reason=step.get("reason") or "agent",
                confidence=1.0, total_latency_ms=step.get("ms") or 0.0, trace=[{k: v for k, v in step.items() if k != "payload"}],
                session_id=session_id, user_id=user.user_id, decision=step["decision"])


@router.post("/reset")
def reset(req: AgentResetRequest, current_user: AuthUser = Depends(get_current_user)):
    _check_domain(req.domain)
    contents = _scenario_contents(req.scenario_id) if req.scenario_id else []
    contents += [(c.channel, c.text) for c in req.contents]
    with _OWNER_LOCK:
        _own(req.session_id, current_user)
        session = agent.reset(req.session_id, req.domain, contents=contents, lang=req.lang,
                              identity={"user_id": current_user.user_id})
        _owners[req.session_id] = current_user.user_id
    return {"session_id": req.session_id, "domain": req.domain, "backend_state": session.backend.snapshot()}


@router.post("/chat")
def agent_chat(req: AgentChatRequest, current_user: AuthUser = Depends(get_current_user)):
    _check_domain(req.domain)
    if req.mode not in MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {list(MODES)}")
    if req.mode != "provenance" and not weaker_modes_allowed():
        raise HTTPException(status_code=403, detail="Firewall modes other than provenance are off. Start the API with AGENT_ALLOW_FIREWALL_OFF=1")
    with _OWNER_LOCK:
        _own(req.session_id, current_user)
        if req.session_id not in agent.sessions:
            agent.reset(req.session_id, req.domain, lang=req.lang, identity={"user_id": current_user.user_id})
            _owners[req.session_id] = current_user.user_id
    result = agent.run(req.session_id, req.text, llm=_llm(req.provider, agent.session(req.session_id).domain), mode=req.mode).to_dict()
    _log(result, req.text, req.session_id, current_user)
    return result


@router.post("/confirm")
def confirm(req: AgentConfirmRequest, current_user: AuthUser = Depends(get_current_user)):
    """The customer confirms or cancels a held action of their own session; reviewers may decide any, like /chat/review."""
    _own(req.session_id, current_user)
    if req.session_id not in agent.sessions:
        raise HTTPException(status_code=404, detail="Unknown agent session")
    pending = agent.session(req.session_id).pending.get(req.review_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="No pending review with that id in this session")
    if not chat._is_reviewer(current_user) and pending.get("review_by") != "user":
        raise HTTPException(status_code=403, detail="This action must be decided by staff on the Security Console")
    try:
        return agent.confirm(req.session_id, req.review_id, req.approve)
    except ReviewNotFound:
        raise HTTPException(status_code=404, detail="No pending review with that id in this session")


@router.get("/state/{session_id}")
def state(session_id: str, current_user: AuthUser = Depends(get_current_user)):
    _own(session_id, current_user)
    if session_id not in agent.sessions:
        raise HTTPException(status_code=404, detail="Unknown agent session")
    return agent.state(session_id)


@router.get("/progress/{session_id}")
def progress(session_id: str, after: int = Query(0, ge=0), current_user: AuthUser = Depends(get_current_user)):
    _own(session_id, current_user)
    if session_id not in agent.sessions or session_id not in _owners:
        raise HTTPException(status_code=404, detail="Unknown agent session")
    return agent.progress(session_id, after)
