# IAM / OAuth2 MVP Demo Guide

This project now includes a lightweight demo IAM flow for local development and showcase purposes. It is intentionally not a production-grade OAuth2/OIDC implementation. The goal is to validate the idea of authenticated users, token-based access, and role-based policy enforcement without needing an external identity provider.

## What this MVP includes

- Local JWT-based authentication using `HS256`
- Bearer token auth on protected routes
- Demo users with roles and permissions
- Route-level protection for chat and console endpoints
- Layer 4 access policy checks based on authenticated user identity
- Example roles:
  - `support_agent`
  - `finance_lead`
  - `security_admin`

## Demo users

The demo users are defined in `api/dependencies/auth.py`.

- `support_agent` / `support_agent_123`
- `finance_lead` / `finance_lead_123`
- `security_admin` / `security_admin_123`

## Start the API

From the project root:

```bash
.\.venv\Scripts\Activate.ps1
python -m uvicorn api.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/docs
```

## Login flow

### 1) Login and get a token

```bash
curl -X POST "http://127.0.0.1:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "support_agent",
    "password": "support_agent_123"
  }'
```

Example response:

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "user_id": "u_support_001",
    "username": "support_agent",
    "roles": ["support_agent"],
    "permissions": ["chat:read", "refund:request"]
  }
}
```

### 2) Call a protected endpoint with Bearer token

```bash
curl -X POST "http://127.0.0.1:8000/chat/message" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "How do I check my order status?"
  }'
```

### 3) Inspect current identity

```bash
curl "http://127.0.0.1:8000/auth/me" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## Role-based examples

### Support agent can talk to chat

```bash
curl -X POST "http://127.0.0.1:8000/chat/message" \
  -H "Authorization: Bearer <support_agent_token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "I need help with a customer issue."}'
```

Support agents can request refunds but are limited by business policy.

### Finance lead can approve refunds

```bash
curl -X POST "http://127.0.0.1:8000/chat/action" \
  -H "Authorization: Bearer <finance_lead_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "action_type": "refund",
    "payload": {
      "user_id": "usr_123",
      "order_id": "ord_999",
      "amount": 180.0,
      "order_value": 150.0,
      "user_role": "finance_lead"
    }
  }'
```

### Security admin can view incidents

```bash
curl "http://127.0.0.1:8000/console/incidents?limit=20" \
  -H "Authorization: Bearer <security_admin_token>"
```

### Unauthorized user is blocked

```bash
curl "http://127.0.0.1:8000/console/stats" \
  -H "Authorization: Bearer <support_agent_token>"
```

This returns `403 Forbidden` because the support agent is not a security admin.

## Behavior of Layer 4

Layer 4 now checks the authenticated identity instead of trusting user-supplied role data in the request body alone.

Examples:

- A support agent may request a small refund.
- A support agent cannot exceed the policy cap for a refund.
- A security admin may access sensitive resources such as `system_prompt`.
- A normal user or unsupported role cannot access sensitive resource endpoints.

## Important limitation of this demo

This is a local MVP and not production-ready identity infrastructure.

It does not include:

- OAuth2 provider integration like Google, GitHub, Microsoft Entra ID, Auth0, or Keycloak
- OIDC discovery and JWKS validation
- Refresh-token rotation
- Secure session management
- Multi-tenancy
- PKI / certificate rotation
- production secret storage

This demo is meant to show the pattern and verify that the API can enforce auth + authorization in a realistic way.

## Next step toward true OAuth2 / OIDC

If you want to upgrade from this MVP to a real enterprise setup, the next phase would be:

1. Add an external IdP (Keycloak, Auth0, Azure AD, Google OAuth, etc.)
2. Replace the local JWT secret with OIDC/JWKS validation
3. Add a `userinfo` or introspection flow
4. Manage role claims from the provider
5. Add refresh/rotation and secure secret storage
6. Add audit logging and admin RBAC

## Quick verification in tests

The project includes focused tests validating the auth flow and Layer 4 policy logic.

```bash
.\.venv\Scripts\python -m pytest -q tests/test_api.py tests/test_layer4.py
```

This should pass for the local demo MVP.
