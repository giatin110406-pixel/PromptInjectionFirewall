"""
Shared contract for every firewall layer.

- Decision: the four final outcomes, ordered by severity.
- LayerResult: the normalized result a layer reports into the trace.
- Source: where a piece of content came from (trust level).

The trace format is append-only: fields are added, never renamed, so the API and
the SOC console keep working while layers migrate to this contract.
"""
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, Iterable, Optional, Union


class Decision(IntEnum):
    """Final outcomes ordered by severity: ALLOW < SANITIZE < REVIEW < BLOCK."""
    ALLOW = 0
    SANITIZE = 1
    REVIEW = 2
    BLOCK = 3

    def __str__(self) -> str:
        return self.name


class Source(str, Enum):
    """Trust level of content entering the engine."""
    USER = "USER"
    UNTRUSTED = "UNTRUSTED"  # RAG documents, email, web pages, tool output
    SYSTEM = "SYSTEM"


# Layers use "PASS" for "nothing found". "ESCALATE" is not a final decision.
_ALIASES = {"PASS": Decision.ALLOW}


def parse_decision(value: Union[str, Decision, None]) -> Optional[Decision]:
    """
    Map a layer's decision string to a Decision.

    Returns None for "ESCALATE" (hand over to the next layer) and for unknown
    values, so callers must treat None explicitly instead of guessing.
    """
    if isinstance(value, Decision):
        return value
    if not isinstance(value, str):
        return None
    key = value.strip().upper()
    if key in _ALIASES:
        return _ALIASES[key]
    return Decision.__members__.get(key)


def max_decision(*decisions: Union[Decision, Iterable[Decision]]) -> Decision:
    """Most severe of the given decisions. An empty input is ALLOW."""
    flat = []
    for item in decisions:
        if isinstance(item, Decision):
            flat.append(item)
        else:
            flat.extend(item)
    return max(flat, default=Decision.ALLOW)


_CORE_FIELDS = ("layer", "decision", "confidence", "reason", "latency_ms", "degraded")


@dataclass
class LayerResult:
    layer: Union[int, str]
    decision: str
    confidence: float = 0.0
    reason: str = ""
    latency_ms: float = 0.0
    degraded: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "LayerResult":
        """Normalize a layer's raw dict. Unknown keys are kept in `details`."""
        details = {k: v for k, v in raw.items() if k not in _CORE_FIELDS}
        return cls(
            layer=raw.get("layer", 0),
            decision=str(raw.get("decision", "ALLOW")),
            confidence=float(raw.get("confidence") or 0.0),
            reason=str(raw.get("reason") or ""),
            latency_ms=float(raw.get("latency_ms") or 0.0),
            degraded=bool(raw.get("degraded", False)),
            details=details,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Flat dict: core fields first, then `details` merged at the top level."""
        out: Dict[str, Any] = {
            "layer": self.layer,
            "decision": self.decision,
            "confidence": self.confidence,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "degraded": self.degraded,
        }
        out.update(self.details)
        return out
