"""
In-memory mock backend (bank, shop, mailbox, documents, files, HR records) for the agent. It keeps state so a demo can
show whether the money moved or stayed put, and logs every action that was really carried out in `executed`.

The only writer is `MockBackend.apply`, and the only caller of that is `Agent._execute` (agent/loop.py), which runs after
the firewall allowed the action or a person confirmed it. Read tools never change state.
"""
import copy
import json
import re
import time
from typing import Any, Dict, List, Optional

from firewall.values import load_trusted_book

DOMAINS = ("shop", "bank", "work")

# Who the agent acts for in each domain: the fields Layer 4 needs that the model does not choose (agent/tools.py).
# The bank values match the demo page (frontend/security-console/pages/demo.jsx BASE_PAYLOAD).
DEFAULT_IDENTITY = {
    "shop": {"user_id": "cus_may_01", "user_role": "support_agent"},
    "bank": {"user_id": "demo_customer", "user_role": "user", "from_account": "0071000555666", "otp_verified": True},
    "work": {"user_id": "emp_001", "user_role": "employee"},
}
WEB_URL = "https://khach.example.com/trang-moi-nhat"
START_BALANCE = 200_000_000.0

_HEADER = re.compile(r"^\s*(From|Subject)\s*:\s*(.+)$", re.I | re.M)


class MockBackend:
    def __init__(self, domain: str = "bank", identity: Optional[Dict[str, Any]] = None):
        if domain not in DOMAINS:
            raise ValueError(f"domain must be one of {DOMAINS}")
        self.domain = domain
        self.identity = dict(DEFAULT_IDENTITY[domain], **(identity or {}))
        self.accounts: Dict[str, float] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.records: Dict[str, str] = {}
        self.inbox: List[Dict[str, Any]] = []
        self.documents: Dict[str, str] = {}
        self.web_pages: Dict[str, str] = {}
        self.tool_results: Dict[str, str] = {}
        self.external_received: Dict[str, float] = {}
        self.sent_emails: List[Dict[str, Any]] = []
        self.shared_files: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []
        self.executed: List[Dict[str, Any]] = []
        self._seed()

    def _seed(self) -> None:
        if self.domain == "bank":
            self.accounts[self.identity["from_account"]] = START_BALANCE
            self.accounts["0451000123456"] = 5_000_000.0           # "Mẹ", a saved recipient (firewall/trusted_book.yaml)
        elif self.domain == "shop":
            self.orders["DH20261031"] = {"value": 60.0, "status": "delivered", "refunded": 0.0}
        else:
            self.records.update(leave_balance="12 ngày phép còn lại", customer_list="(danh sách khách hàng nội bộ)")

    # ---------------------------------------------------------------- content the agent can read
    def load_content(self, channel: str, text: str) -> None:
        """Put untrusted content where the matching read tool finds it. `channel`: email, web, document, review,
        tool_json (as in data/eval/v4)."""
        if channel == "email":
            fields = {m.group(1).lower(): m.group(2).strip() for m in _HEADER.finditer(text)}
            self.inbox.append({"id": f"m{len(self.inbox) + 1}", "from": fields.get("from", "unknown@example.com"),
                               "subject": fields.get("subject", "(no subject)"), "body": text})
        elif channel == "web":
            self.web_pages[WEB_URL] = text
        elif channel in ("document", "review"):
            self.documents[f"doc-{len(self.documents) + 1}"] = text
        elif channel in ("tool_json", "tool"):
            self.tool_results["latest"] = text
        else:
            raise ValueError(f"unknown channel '{channel}'")

    def describe_resources(self) -> str:
        """What a mail client or file browser would show: lets the model know there is something to open."""
        lines = []
        if self.inbox:
            # Mail headers are attacker-controlled too. Only server-generated IDs belong in the system prompt;
            # list_inbox/read_email expose headers through the same scanned path as the body.
            lines.append("Hộp thư có thư chưa đọc: " + ", ".join(m['id'] for m in self.inbox))
        if self.documents:
            lines.append("Kho tài liệu có: " + ", ".join(self.documents))
        if self.web_pages:
            lines.append("Trang web khách gửi: " + ", ".join(self.web_pages))
        if self.tool_results:
            lines.append("Có một kết quả tra cứu đơn hàng (mã 'latest').")
        return "\n".join(lines)

    def read(self, tool: str, args: Dict[str, Any]) -> str:
        if tool == "list_inbox":
            return "\n".join(f"{m['id']} | {m['from']} | {m['subject']}" for m in self.inbox) or "(hộp thư trống)"
        if tool == "lookup_contact":
            name = args["name"].strip().casefold()
            # Same per-user saved book that Layer 4 uses. External documents cannot create contacts.
            if (name in ("mẹ", "mother", "mom") and load_trusted_book().contains(
                    self.identity["user_id"], "0451000123456")):
                return json.dumps({"name": "Mẹ / Mother", "to_account": "0451000123456", "bank_code": "VCB"},
                                  ensure_ascii=False)
            return "Không tìm thấy người nhận đã lưu."
        if tool == "read_email":
            key = args["email_id"]
            mail = self.inbox[-1] if key == "latest" and self.inbox else next((m for m in self.inbox if m["id"] == key), None)
            return mail["body"] if mail else f"Không tìm thấy thư '{key}'."
        if tool == "open_document":
            key = args["document_id"]
            if key == "latest" and self.documents:
                return list(self.documents.values())[-1]
            return self.documents.get(key, f"Không tìm thấy tài liệu '{key}'.")
        if tool == "fetch_url":
            return self.web_pages.get(args["url"]) or (list(self.web_pages.values())[-1] if args["url"] == "latest" and self.web_pages
                                                       else "Không tải được trang (404).")
        if tool == "lookup_order":
            key = args["order_id"]
            if key in self.tool_results:
                return self.tool_results[key]
            if key in self.orders:
                o = self.orders[key]
                return f"Đơn {key}: giá trị {o['value']:g} USD, trạng thái {o['status']}, đã hoàn {o['refunded']:g} USD."
            return self.tool_results.get("latest", f"Không tìm thấy đơn '{key}'.") if key == "latest" else f"Không tìm thấy đơn '{key}'."
        raise KeyError(tool)

    def order_value(self, order_id: str) -> Optional[float]:
        order = self.orders.get(order_id)
        return order["value"] if order else None

    # ---------------------------------------------------------------- the one writer
    def apply(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Carry out an action. Called only by Agent._execute. Returns {"ok", "message"}; a refused one (not enough money)
        changes nothing and is not logged as executed."""
        result = self._do(action, payload)
        if result["ok"]:
            self.executed.append({"type": action, "payload": copy.deepcopy(payload), "at": time.time()})
        return result

    def _do(self, action: str, p: Dict[str, Any]) -> Dict[str, Any]:
        ok = lambda msg: {"ok": True, "message": msg}      # noqa: E731
        if action in ("transfer_money", "transfer"):
            src, dst, amount = p["from_account"], p["to_account"], float(p["amount"])
            if self.accounts.get(src, 0.0) < amount:
                return {"ok": False, "message": "Số dư không đủ."}
            self.accounts[src] -= amount
            if dst in self.accounts:
                self.accounts[dst] += amount
            else:
                self.external_received[dst] = self.external_received.get(dst, 0.0) + amount
            return ok(f"Đã chuyển {amount:,.0f} {p.get('currency', 'VND')} tới {dst}. Số dư còn {self.accounts[src]:,.0f}.")
        if action == "refund":
            order = self.orders.setdefault(p["order_id"], {"value": float(p["order_value"]), "status": "delivered", "refunded": 0.0})
            order["refunded"] += float(p["amount"])
            return ok(f"Đã hoàn {float(p['amount']):g} USD cho đơn {p['order_id']}.")
        if action == "send_email":
            self.sent_emails.append({k: p.get(k) for k in ("to", "cc", "subject", "body", "attachments")})
            return ok("Đã gửi email tới " + ", ".join(p.get("to") or []) + ".")
        if action == "share_file":
            self.shared_files.append({k: p.get(k) for k in ("file_id", "share_with", "permission")})
            return ok(f"Đã chia sẻ file {p['file_id']}.")
        if action == "post_message":
            self.messages.append({"target": p["target"], "text": p["text"]})
            return ok(f"Đã đăng tin tới {p['target']}.")
        if action == "data_access":
            return ok(self.records.get(p["resource"], f"(dữ liệu '{p['resource']}')"))
        if action in ("password_reset", "account_recovery"):
            return ok(f"Đã xử lý {action} cho {p['target_account']}.")
        if action in ("voucher_apply", "coupon_apply"):
            return ok(f"Đã áp mã {p['voucher_code']} cho đơn {p['order_id']}.")
        if action == "http_request":
            return ok(f"Đã gọi {p.get('method', 'GET')} {p['url']}.")
        return {"ok": False, "message": f"Không hỗ trợ hành động '{action}'."}

    def snapshot(self) -> Dict[str, Any]:
        """Backend state for the demo panel and tests."""
        return {
            "domain": self.domain,
            "balances": {k: round(v, 2) for k, v in self.accounts.items()},
            "external_received": dict(self.external_received),
            "orders": copy.deepcopy(self.orders),
            "sent_emails": len(self.sent_emails), "shared_files": list(self.shared_files), "messages": list(self.messages),
            "inbox": [{"id": m["id"], "from": m["from"], "subject": m["subject"]} for m in self.inbox],
            "executed": [{"type": e["type"], "payload": e["payload"]} for e in self.executed],
        }
