"""
Egress control (WP3 of docs/implementation_plan_v4_vi.md): actions that send data out of the system.

Layer 5 checks what the agent SAYS. An agent can also leak through what it DOES: send an email, call a URL, post to a
chat channel, share a file. The InjecAgent "data stealing" cases all end that way: read private data, then
GmailSendEmail to the attacker. Those actions have class `communicate` in policies.yaml and go through this module:

  destinations   the payload keys named by `provenance_fields` (the recipient, the URL, the channel), list values
                 flattened. A destination is TRUSTED when it is on the egress allow-list (the company's own domains
                 and channels, subdomains included), typed by the user, or in their saved recipients.
  content        the payload keys named by `content_fields` (subject, body, attachments...), scanned with the
                 detectors of Layer 5 (firewall/output_guard.py).

Decisions added by the gate (firewall/action_gate.py), before the usual taint/exposure checks:
  - a secret or a canary token in the content, sent to any destination outside the allow-list: BLOCK, in every
    session. No legitimate flow mails an API key to an outside address.
  - personal data (phone, email, card, national ID, bank account) in the content, in a session that read untrusted
    content, sent to a destination that is not trusted: BLOCK. This is the data-stealing pattern.
  - otherwise the exposure check applies as for money: an untrusted destination in an exposed session is a REVIEW.
"""
import ipaddress
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from firewall.output_guard import OutputGuard
from firewall.values import normalize_value

EGRESS_CLASS = "communicate"


def flatten(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [v for v in value if v not in (None, "")]
    return [value]


def private_host(url: str) -> bool:
    """True for a URL whose host is an IP literal on a private, loopback, link-local or reserved range, or localhost
    (an agent asked to call http://169.254.169.254/ is reading the cloud metadata service, not the web)."""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


class EgressGuard:
    def __init__(self, allowlist: Iterable[str] = (), guard: Optional[OutputGuard] = None):
        self.allowlist = {k for k in (normalize_value(v) for v in allowlist or ()) if k}
        self.guard = guard or OutputGuard()

    def allowlisted(self, value: Any) -> bool:
        key = normalize_value(value)
        if not key:
            return False
        domain = key.split("@", 1)[1] if "@" in key else key
        return any(key == entry or domain == entry or domain.endswith("." + entry) for entry in self.allowlist)

    @staticmethod
    def destinations(rule: Dict[str, Any], payload: Dict[str, Any]) -> List[Tuple[str, Any]]:
        return [(field, v) for field in rule.get("provenance_fields", []) for v in flatten(payload.get(field))]

    @staticmethod
    def content(rule: Dict[str, Any], payload: Dict[str, Any]) -> str:
        return "\n".join(str(v) for field in rule.get("content_fields", []) for v in flatten(payload.get(field)))

    def findings(self, text: str) -> Dict[str, List[str]]:
        """{"secret": [...], "pii": [...]} found in the outgoing content (kinds, not values)."""
        out: Dict[str, List[str]] = {"secret": [], "pii": []}
        if not text.strip():
            return out
        for f in self.guard.check(text)["findings"]:
            if f["type"] in ("secret", "canary_leak"):
                out["secret"].append(f.get("kind", f["type"]))
            elif f["type"] == "pii":
                out["pii"].append(f["kind"])
        return {k: sorted(set(v)) for k, v in out.items()}
