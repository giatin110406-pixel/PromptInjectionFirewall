"""
Layer 4: Security Policy Validator.
Uses Pydantic v2 to validate actions and prevent business logic bypasses
(e.g., unauthorized refunds, illegal money transfers, unauthorized password resets,
excessive coupon/voucher discounts, and illegal privilege escalation).
Independent of language (validates structured JSON schemas).
"""
import re
from typing import Dict, Any, List, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo

from api.schemas import AuthUser
from firewall.egress import private_host


class RefundRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    order_value: float = Field(..., gt=0)
    user_role: str = Field(..., min_length=1)
    reason: Optional[str] = "Customer return"

    @field_validator("user_role")
    @classmethod
    def validate_role_authorization(cls, v: str) -> str:
        role = v.strip().lower()
        allowed_roles = {"support_agent", "supervisor", "admin", "finance_lead"}
        if role not in allowed_roles:
            raise ValueError(f"Role '{v}' is not authorized to process refunds")
        return v

    @model_validator(mode="after")
    def validate_business_policy(self) -> "RefundRequest":
        # Policy: Refund amount cannot exceed 110% of the original order value
        if self.amount > (self.order_value * 1.10):
            raise ValueError(
                f"Refund amount ${self.amount:.2f} exceeds policy limit of 110% of order value (${self.order_value * 1.10:.2f})"
            )
        # Support agents can only approve refunds up to $200 without supervisor
        if self.user_role.lower() == "support_agent" and self.amount > 200.0:
            raise ValueError(f"Support agents cannot approve refunds over $200.00 (requested: ${self.amount:.2f})")
        return self


class DataAccessRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    user_role: str = Field(..., min_length=1)
    resource: str = Field(..., min_length=1)
    query_scope: str = Field("own_account")

    @field_validator("resource")
    @classmethod
    def validate_sensitive_resource(cls, v: str, info: ValidationInfo) -> str:
        restricted = {"system_prompt", "credentials", "database_dump", "internal_keys", "shadow_file"}
        if v.lower() in restricted:
            role = info.data.get("user_role", "").lower()
            if role != "security_admin":
                raise ValueError(f"Access to sensitive resource '{v}' forbidden for role '{role}'")
        return v


class TransferMoneyRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    user_role: str = Field(..., min_length=1)
    from_account: str = Field(..., min_length=3)
    to_account: str = Field(..., min_length=3)
    bank_code: str = Field(..., min_length=2)
    amount: float = Field(..., gt=0)
    currency: str = Field("VND", min_length=2)
    requires_otp: bool = True
    otp_verified: bool = False

    @field_validator("user_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        allowed = {"user", "customer_support", "finance_officer", "treasury_lead", "admin"}
        if role not in allowed:
            raise ValueError(f"Role '{v}' is not authorized to initiate transfers")
        return v

    @model_validator(mode="after")
    def validate_transfer_policy(self) -> "TransferMoneyRequest":
        if self.from_account.strip().lower() == self.to_account.strip().lower():
            raise ValueError("Sender and recipient accounts cannot be identical")

        is_vnd = self.currency.upper() == "VND"
        max_user_limit = 50_000_000.0 if is_vnd else 2_000.0
        otp_threshold = 10_000_000.0 if is_vnd else 500.0
        high_value_threshold = 100_000_000.0 if is_vnd else 5_000.0

        # Normal users cannot exceed max user transaction limit
        if self.user_role.lower() == "user" and self.amount > max_user_limit:
            raise ValueError(
                f"Transfer amount {self.amount:,.0f} {self.currency} exceeds single transaction limit "
                f"of {max_user_limit:,.0f} {self.currency} for role 'user'"
            )

        # High-value transactions require finance officer or higher
        if self.amount > high_value_threshold and self.user_role.lower() not in {"finance_officer", "treasury_lead", "admin"}:
            raise ValueError(
                f"High-value transfers exceeding {high_value_threshold:,.0f} {self.currency} require finance_officer authorization"
            )

        # OTP is mandatory for transactions above threshold
        if self.amount >= otp_threshold and not self.otp_verified:
            raise ValueError(
                f"Transfers of {self.amount:,.0f} {self.currency} require mandatory 2FA OTP verification"
            )

        return self


class AccountRecoveryRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    target_account: str = Field(..., min_length=1)
    user_role: str = Field(..., min_length=1)
    verification_method: str = Field(..., min_length=2)
    identity_confirmed: bool = False
    ticket_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_recovery_policy(self) -> "AccountRecoveryRequest":
        if not self.identity_confirmed:
            raise ValueError("Identity must be strictly verified before recovering account or resetting password")

        method = self.verification_method.lower()
        if method == "support_override":
            if self.user_role.lower() not in {"security_admin", "supervisor"}:
                raise ValueError("Support override for account recovery is restricted to security_admin or supervisor")
            if not self.ticket_id or len(self.ticket_id.strip()) < 3:
                raise ValueError("Valid support ticket ID is mandatory for manual account recovery override")
        return self


class VoucherApplyRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    order_total: float = Field(..., gt=0)
    voucher_code: str = Field(..., min_length=2)
    discount_percent: Optional[float] = Field(default=None, ge=0, le=100)
    discount_amount: Optional[float] = Field(default=None, ge=0)
    user_role: str = Field("customer")

    @model_validator(mode="after")
    def validate_voucher_policy(self) -> "VoucherApplyRequest":
        # Check percentage discount constraint (cannot exceed 70% without marketing_manager / admin)
        if self.discount_percent is not None:
            if self.discount_percent > 70.0 and self.user_role.lower() not in {"marketing_manager", "admin"}:
                raise ValueError(
                    f"Voucher discount {self.discount_percent:.1f}% exceeds maximum allowable limit of 70% "
                    f"without marketing_manager authorization"
                )

        # Check flat discount amount
        if self.discount_amount is not None:
            if self.discount_amount > self.order_total:
                raise ValueError("Discount amount cannot exceed total order value")
            # Max single flat voucher without manager: 5,000,000 VND / $250
            if self.discount_amount > 5_000_000.0 and self.user_role.lower() not in {"marketing_manager", "admin"}:
                raise ValueError(
                    f"Flat voucher discount exceeds policy limit of 5,000,000 without manager approval"
                )
        return self


class AccessControlRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    operator_role: str = Field(..., min_length=1)
    target_user_id: str = Field(..., min_length=1)
    requested_role: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=10)
    ticket_id: str = Field(..., min_length=4)

    @model_validator(mode="after")
    def validate_privilege_policy(self) -> "AccessControlRequest":
        # Strictly forbid self-escalation
        if self.operator_id.strip().lower() == self.target_user_id.strip().lower():
            raise ValueError("Self-escalation of privileges is strictly prohibited by security policy")

        high_privilege_roles = {"admin", "super_admin", "root", "system_security"}
        if self.requested_role.lower() in high_privilege_roles:
            if self.operator_role.lower() not in {"super_admin", "system_security"}:
                raise ValueError(
                    f"Granting '{self.requested_role}' privilege requires authorization from 'super_admin'"
                )
        return self


# ---------------------------------------------------------------- egress (WP3): actions that send data out
_EMAIL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAX_RECIPIENTS = 20


def _as_list(value: Union[str, List[str], None]) -> List[str]:
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return [str(v).strip() for v in items if str(v).strip()]


def _web_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Only http(s) URLs with a host may be called, not '{url[:60]}'")
    if private_host(url):
        raise ValueError(f"Calls to local or private network addresses are forbidden ('{parsed.hostname}')")
    return url


class SendEmailRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    to: List[str]
    cc: List[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    attachments: List[str] = Field(default_factory=list)
    user_role: str = Field("user")

    @field_validator("to", "cc", mode="before")
    @classmethod
    def listify(cls, v):
        return _as_list(v)

    @model_validator(mode="after")
    def validate_recipients(self) -> "SendEmailRequest":
        recipients = self.to + self.cc
        if not self.to:
            raise ValueError("An email needs at least one recipient")
        if len(recipients) > MAX_RECIPIENTS:
            raise ValueError(f"At most {MAX_RECIPIENTS} recipients per email (got {len(recipients)})")
        bad = [r for r in recipients if not _EMAIL_ADDRESS.fullmatch(r)]
        if bad:
            raise ValueError(f"Not an email address: '{bad[0][:60]}'")
        return self


class HttpRequestRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=8)
    method: str = "GET"
    body: str = ""
    user_role: str = Field("user")

    @model_validator(mode="after")
    def validate_request(self) -> "HttpRequestRequest":
        if self.method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError(f"HTTP method '{self.method}' is not allowed")
        _web_url(self.url)
        return self


class PostMessageRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=2, description="a channel ('#support'), a user handle or a webhook URL")
    text: str = Field(..., min_length=1)
    user_role: str = Field("user")

    @model_validator(mode="after")
    def validate_target(self) -> "PostMessageRequest":
        if "://" in self.target:
            _web_url(self.target)
        return self


class ShareFileRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    file_id: str = Field(..., min_length=1)
    share_with: List[str]
    permission: str = "view"
    user_role: str = Field("user")

    @field_validator("share_with", mode="before")
    @classmethod
    def listify(cls, v):
        return _as_list(v)

    @model_validator(mode="after")
    def validate_share(self) -> "ShareFileRequest":
        if not self.share_with:
            raise ValueError("Nobody to share the file with")
        if self.permission.lower() not in {"view", "comment", "edit"}:
            raise ValueError(f"Share permission '{self.permission}' is not allowed")
        if any(s.lower() in {"anyone", "public", "*"} for s in self.share_with):
            raise ValueError("Public links are not allowed: share with named people or domains")
        return self


def _clean_error(exc: Exception) -> str:
    """One readable sentence for a rejected action (pydantic's own text carries input dumps and a docs URL)."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            messages = [str(e.get("msg", "")).removeprefix("Value error, ").strip() for e in errors()]
            messages = [m for m in messages if m]
            if messages:
                return "; ".join(messages)
        except Exception:
            pass
    return str(exc)


class Layer4Validator:
    """Policy Validator enforcing strict boundary and business rule checks."""

    ACTION_MODELS = {
        "refund": RefundRequest,
        "data_access": DataAccessRequest,
        "transfer_money": TransferMoneyRequest,
        "transfer": TransferMoneyRequest,
        "account_recovery": AccountRecoveryRequest,
        "password_reset": AccountRecoveryRequest,
        "voucher_apply": VoucherApplyRequest,
        "coupon_apply": VoucherApplyRequest,
        "role_escalation": AccessControlRequest,
        "access_control": AccessControlRequest,
        "send_email": SendEmailRequest,
        "http_request": HttpRequestRequest,
        "post_message": PostMessageRequest,
        "share_file": ShareFileRequest,
    }

    LEGACY_ROLE_PERMISSIONS = {
        "support_agent": {"chat:read", "refund:request"},
        "finance_lead": {"chat:read", "refund:request", "refund:approve", "refund:approve_over_200"},
        "security_admin": {"chat:read", "data_access:system_prompt", "data_access:credentials"},
    }

    def _effective_roles_and_permissions(self, payload: Dict[str, Any], user: Optional[AuthUser]):
        if user is not None:
            return {
                role.lower() for role in user.roles
            }, {
                permission.lower() for permission in user.permissions
            }

        requested_role = str(payload.get("user_role", "")).strip()
        roles = {requested_role.lower()} if requested_role else set()
        permissions = set()

        legacy_aliases = {
            "supervisor": {"finance_lead", "support_agent"},
            "admin": {"finance_lead", "support_agent"},
        }

        for role in set(roles):
            permissions.update({p.lower() for p in self.LEGACY_ROLE_PERMISSIONS.get(role, set())})
            for alias, mapped_roles in legacy_aliases.items():
                if role == alias:
                    for mapped_role in mapped_roles:
                        roles.add(mapped_role)
                        permissions.update({p.lower() for p in self.LEGACY_ROLE_PERMISSIONS.get(mapped_role, set())})

        return roles, permissions

    def validate_action(self, action_type: str, payload: Dict[str, Any], user: Optional[AuthUser] = None) -> Dict[str, Any]:
        """
        Validates the proposed action against predefined policy schemas and IAM roles.
        Returns:
            dict: { "layer": 4, "decision": "ALLOW" | "BLOCK", "reason": str | None }
        """
        model_cls = self.ACTION_MODELS.get(action_type.lower())
        if not model_cls:
            return {
                "layer": 4,
                "decision": "BLOCK",
                "reason": f"Unknown action type: '{action_type}'"
            }

        payload = dict(payload or {})
        user_roles, user_permissions = self._effective_roles_and_permissions(payload, user)

        if user is not None:
            payload.setdefault("user_role", next(iter(user.roles), "guest"))
        elif not payload.get("user_role"):
            payload["user_role"] = "guest"

        try:
            if action_type.lower() == "refund":
                if not user_roles:
                    raise ValueError("Authentication required for refund action")
                if "finance_lead" not in user_roles and "support_agent" not in user_roles:
                    raise ValueError(f"Role '{payload.get('user_role')}' is not authorized to process refunds")
                if "support_agent" in user_roles and "refund:approve_over_200" not in user_permissions:
                    amount = float(payload.get("amount", 0.0))
                    if amount > 200.0:
                        raise ValueError("Support agents cannot approve refunds over $200.00")
                if "supervisor" in user_roles or "admin" in user_roles:
                    user_roles.add("finance_lead")
                    user_permissions.update({"refund:approve_over_200", "refund:approve"})

            if action_type.lower() == "data_access":
                resource = str(payload.get("resource", "")).lower()
                if resource in {"system_prompt", "credentials", "database_dump", "internal_keys", "shadow_file"}:
                    if "security_admin" not in user_roles and "data_access:system_prompt" not in user_permissions:
                        raise ValueError(f"Access to sensitive resource '{resource}' forbidden for role '{payload.get('user_role', 'guest')}'")

            validated = model_cls(**payload)
            return {
                "layer": 4,
                "decision": "ALLOW",
                "validated_data": validated.model_dump(),
                "reason": None
            }
        except Exception as e:
            return {
                "layer": 4,
                "decision": "BLOCK",
                "reason": _clean_error(e)
            }
