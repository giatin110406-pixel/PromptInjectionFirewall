"""
Layer 4: Security Policy Validator.
Uses Pydantic v2 to validate actions and prevent business logic bypasses
(e.g., unauthorized refunds, illegal money transfers, unauthorized password resets,
excessive coupon/voucher discounts, and illegal privilege escalation).
Independent of language (validates structured JSON schemas).
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo

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
    }

    def validate_action(self, action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates the proposed action against predefined policy schemas.
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

        try:
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
                "reason": str(e)
            }
