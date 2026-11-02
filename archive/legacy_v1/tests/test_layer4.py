import pytest
from firewall.layer4 import Layer4Validator

@pytest.fixture
def validator():
    return Layer4Validator()

def test_valid_refund_allowed(validator):
    payload = {
        "user_id": "usr_123",
        "order_id": "ord_999",
        "amount": 50.0,
        "order_value": 50.0,
        "user_role": "support_agent"
    }
    res = validator.validate_action("refund", payload)
    assert res["decision"] == "ALLOW"
    assert res["reason"] is None

def test_refund_exceeding_110_percent_blocked(validator):
    payload = {
        "user_id": "usr_123",
        "order_id": "ord_999",
        "amount": 200.0,  # exceeds $100 * 1.1 = $110
        "order_value": 100.0,
        "user_role": "supervisor"
    }
    res = validator.validate_action("refund", payload)
    assert res["decision"] == "BLOCK"
    assert "exceeds policy limit" in res["reason"]

def test_support_agent_over_limit_blocked(validator):
    payload = {
        "user_id": "usr_123",
        "order_id": "ord_999",
        "amount": 250.0,
        "order_value": 250.0,
        "user_role": "support_agent"  # support agent max is $200
    }
    res = validator.validate_action("refund", payload)
    assert res["decision"] == "BLOCK"
    assert "cannot approve refunds over $200" in res["reason"]

def test_unauthorized_role_blocked(validator):
    payload = {
        "user_id": "usr_123",
        "order_id": "ord_999",
        "amount": 30.0,
        "order_value": 30.0,
        "user_role": "guest"
    }
    res = validator.validate_action("refund", payload)
    assert res["decision"] == "BLOCK"
    assert "is not authorized" in res["reason"]

def test_sensitive_data_access_blocked_for_normal_user(validator):
    payload = {
        "user_id": "usr_456",
        "user_role": "support_agent",
        "resource": "database_dump"
    }
    res = validator.validate_action("data_access", payload)
    assert res["decision"] == "BLOCK"
    assert "forbidden" in res["reason"]

def test_sensitive_data_access_allowed_for_security_admin(validator):
    payload = {
        "user_id": "sec_001",
        "user_role": "security_admin",
        "resource": "system_prompt"
    }
    res = validator.validate_action("data_access", payload)
    assert res["decision"] == "ALLOW"
