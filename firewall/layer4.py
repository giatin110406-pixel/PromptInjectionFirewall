"""
Layer 4: Policy Validator.
Uses Pydantic v2 to validate actions and prevent business logic bypasses
(e.g., unauthorized refunds, excessive discount overrides, illegal role escalation).
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

class Layer4Validator:
    """Policy Validator enforcing strict boundary and business rule checks."""

    ACTION_MODELS = {
        "refund": RefundRequest,
        "data_access": DataAccessRequest,
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
