"""/agent/* through TestClient: auth, the scripted agent on demo scenarios, confirm, session ownership."""
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import agent as agent_route

RUN = uuid.uuid4().hex[:6]       # session ids are unique per run: no state can leak between runs


@pytest.fixture
def client():
    yield TestClient(app)
    # the review queue is shared with tests/test_api.py, which counts a customer's pending items: leave none behind
    queue = agent_route.chat.orchestrator.review_queue
    for item in queue.list("pending"):
        if str(item.get("session_id", "")).startswith("api-"):
            queue.decide(item["id"], False, reviewer="test cleanup")


def headers(client, user="khach_hang", password="khach_hang_123"):
    res = client.post("/auth/login", json={"username": user, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


BANK_USER = "Đóng tiền phòng tháng này theo tin nhắn của cô Hạnh giúp mình"
LEGIT_USER = "Gửi mẹ 2 triệu như mọi tháng"


def test_agent_routes_need_auth(client):
    assert client.post("/agent/chat", json={"session_id": "a", "text": "hi"}).status_code in (401, 403)
    assert client.get("/agent/state/a").status_code in (401, 403)


def test_busy_session_returns_409_instead_of_waiting_forever(client, monkeypatch):
    from agent.loop import SessionBusyError
    monkeypatch.setattr(agent_route, "_llm", lambda *args, **kwargs: None)
    def busy(*args, **kwargs):
        raise SessionBusyError("Phiên đang xử lý yêu cầu trước")
    monkeypatch.setattr(agent_route.agent, "run", busy)
    result = client.post("/agent/chat", json={"session_id": "api-busy-" + RUN, "text": "hello"}, headers=headers(client))
    assert result.status_code == 409 and "Phiên đang xử lý" in result.json()["detail"]


def test_unknown_domain_and_mode_are_rejected(client):
    h = headers(client)
    assert client.post("/agent/reset", json={"session_id": "api-d-" + RUN, "domain": "moon"}, headers=h).status_code == 422
    assert client.post("/agent/chat", json={"session_id": "api-d-" + RUN, "text": "x", "mode": "weird"}, headers=h).status_code == 422
    assert client.post("/agent/reset", json={"session_id": "api-d-" + RUN, "scenario_id": "nope"}, headers=h).status_code == 404


def test_attack_scenario_is_stopped_and_balance_is_unchanged(client):
    h = headers(client)
    sid = "api-atk-" + RUN
    assert client.post("/agent/reset", json={"session_id": sid, "domain": "bank", "scenario_id": "bank-attack"}, headers=h).status_code == 200
    out = client.post("/agent/chat", json={"session_id": sid, "text": BANK_USER, "provider": "scripted"}, headers=h).json()
    read = next(s for s in out["steps"] if s["kind"] == "tool_read")
    assert read["firewall"]["tainted"] and read["firewall"]["session_level"] == "tainted"
    # the hidden instruction was cut out before the model saw the email, so the scripted agent finds no account to pay
    assert out["executed"] == [] and out["backend_state"]["external_received"] == {}


def test_firewall_off_is_refused_unless_the_operator_allows_it(client, monkeypatch):
    monkeypatch.delenv("AGENT_ALLOW_FIREWALL_OFF", raising=False)
    h = headers(client)
    for mode in ("off", "detection"):
        r = client.post("/agent/chat", json={"session_id": "api-gate-" + RUN, "text": BANK_USER, "mode": mode, "provider": "scripted"}, headers=h)
        assert r.status_code == 403


def test_same_scenario_without_firewall_moves_the_money(client, monkeypatch):
    monkeypatch.setenv("AGENT_ALLOW_FIREWALL_OFF", "1")
    h = headers(client)
    sid = "api-off-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "bank", "scenario_id": "bank-attack"}, headers=h)
    out = client.post("/agent/chat", json={"session_id": sid, "text": BANK_USER, "mode": "off", "provider": "scripted"}, headers=h).json()
    assert out["backend_state"]["external_received"] == {"000088041003": 2_400_000}


def test_value_case_waits_for_the_customer_who_confirms(client):
    h = headers(client)
    sid = "api-val-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "bank", "scenario_id": "bank-value"}, headers=h)
    out = client.post("/agent/chat", json={"session_id": sid, "text": BANK_USER, "provider": "scripted"}, headers=h).json()
    review = out["pending_review"]
    assert review and review["review_by"] == "user" and out["executed"] == []
    state = client.get(f"/agent/state/{sid}", headers=h).json()
    assert state["pending"][0]["review_id"] == review["review_id"]
    res = client.post("/agent/confirm", json={"session_id": sid, "review_id": review["review_id"], "approve": True}, headers=h)
    assert res.status_code == 200 and res.json()["executed"]
    assert res.json()["backend_state"]["external_received"] == {"000088041004": 2_400_000}
    again = client.post("/agent/confirm", json={"session_id": sid, "review_id": review["review_id"], "approve": True}, headers=h)
    assert again.status_code == 404


def test_shop_fallback_reads_actual_resource_and_handles_datamarked_order(client):
    h = headers(client, "support_agent", "support_agent_123")
    sid = "api-shop-value-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "shop", "scenario_id": "shop-value"}, headers=h)
    out = client.post("/agent/chat", json={"session_id": sid, "domain": "shop",
        "text": "Bạn xem giúp phiếu giao hàng vừa nhận nhé.", "provider": "scripted"}, headers=h).json()
    assert out["pending_review"]["review_by"] == "staff"
    assert out["pending_review"]["payload"]["order_id"] == "DH88041002"
    items = client.get("/chat/review?status=all", headers=h).json()
    assert any(item["id"] == out["pending_review"]["review_id"] for item in items)
    assert not out["executed"]


def test_cancel_executes_nothing(client):
    h = headers(client)
    sid = "api-cancel-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "bank", "scenario_id": "bank-value"}, headers=h)
    review = client.post("/agent/chat", json={"session_id": sid, "text": BANK_USER}, headers=h).json()["pending_review"]
    res = client.post("/agent/confirm", json={"session_id": sid, "review_id": review["review_id"], "approve": False}, headers=h).json()
    assert res["status"] == "rejected" and res["backend_state"]["external_received"] == {}


def test_legit_transfer_runs_at_once(client):
    h = headers(client)
    out = client.post("/agent/chat", json={"session_id": "api-ok-" + RUN, "text": LEGIT_USER, "domain": "bank"}, headers=h).json()
    assert out["pending_review"] is None and [e["type"] for e in out["executed"]] == ["transfer_money"]
    assert out["backend_state"]["balances"]["0451000123456"] == 7_000_000


def test_staff_review_cannot_be_confirmed_by_the_customer(client):
    h = headers(client, "nhan_vien", "nhan_vien_123")
    sid = "api-staff-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "work", "scenario_id": "work-value"}, headers=h)
    out = client.post("/agent/chat", json={"session_id": sid, "text": "Bạn tóm tắt giúp ticket máy in nhé."}, headers=h).json()
    review = out["pending_review"]
    assert review and review["review_by"] == "staff"
    res = client.post("/agent/confirm", json={"session_id": sid, "review_id": review["review_id"], "approve": True}, headers=h)
    assert res.status_code == 403
    admin = headers(client, "security_admin", "security_admin_123")
    admin_owner = client.post("/agent/confirm", json={"session_id": sid, "review_id": review["review_id"], "approve": True}, headers=admin)
    assert admin_owner.status_code == 403       # the session belongs to another user, even for a reviewer


def test_session_belongs_to_its_creator(client):
    a, b = headers(client), headers(client, "support_agent", "support_agent_123")
    client.post("/agent/reset", json={"session_id": "api-own-" + RUN, "domain": "bank"}, headers=a)
    assert client.get("/agent/state/api-own-" + RUN, headers=b).status_code == 403
    assert client.post("/agent/chat", json={"session_id": "api-own-" + RUN, "text": "xin chào"}, headers=b).status_code == 403
    assert client.get("/agent/state/missing", headers=a).status_code == 404


def test_pasted_document_is_read_by_the_agent(client):
    h = headers(client)
    sid = "api-paste-" + RUN
    client.post("/agent/reset", json={"session_id": sid, "domain": "bank", "contents": [
        {"channel": "email", "text": "Thông báo tiền phòng\nSố tiền: 2.400.000đ\nTài khoản nhận: 000088041009"}]}, headers=h)
    out = client.post("/agent/chat", json={"session_id": sid, "text": BANK_USER}, headers=h).json()
    reads = [s for s in out["steps"] if s["kind"] == "tool_read"]
    assert reads and reads[0]["firewall"] is not None
    assert out["pending_review"]["payload"]["to_account"] == "000088041009"


def test_provider_without_a_key_is_a_clear_503(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("agent.llm.load_env_file", lambda *a, **k: 0)
    agent_route._llms.clear()
    res = client.post("/agent/chat", json={"session_id": "api-503-" + RUN, "text": "xin chào", "provider": "gemini"}, headers=headers(client))
    assert res.status_code == 503 and "GEMINI_API_KEY" in res.json()["detail"]
