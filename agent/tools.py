"""
Tool definitions (OpenAI function-calling schema) for the agent.

Read tools return text from the backend; the agent loop scans that text with the firewall (process_context) before the
model sees it. Action tools change the backend; their parameters carry the same names as the payload that
firewall/layer4.py validates (Layer4Validator.ACTION_MODELS), so the arguments go to validate_action unchanged. The fields
the system knows (who is logged in, the source account, whether the OTP was verified) are never parameters: they come
from the session identity, so the model cannot fill or override them.
"""
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple

SYSTEM_FIELDS = ("user_id", "user_role", "from_account", "otp_verified", "identity_confirmed")

STR, NUM, STRS = "string", "number", "array"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: str                                   # "read" or "action"
    description: str
    params: Dict[str, Tuple[str, str]] = field(default_factory=dict)      # name -> (type, description)
    required: Tuple[str, ...] = ()
    source: str = "tool"                        # what the firewall calls the content of a read tool (email, web, document, tool)


def _spec(name, kind, description, params=None, required=(), source="tool"):
    return ToolSpec(name, kind, description, params or {}, tuple(required), source)


TOOLS: Dict[str, ToolSpec] = {t.name: t for t in [
    _spec("list_inbox", "read", "Liệt kê thư trong hộp thư (id, người gửi, tiêu đề).", source="email"),
    _spec("read_email", "read", "Đọc nội dung một email.", {"email_id": (STR, "id thư, hoặc 'latest' cho thư mới nhất")},
          ["email_id"], "email"),
    _spec("open_document", "read", "Mở một tài liệu trong kho tài liệu.", {"document_id": (STR, "id tài liệu, hoặc 'latest'")},
          ["document_id"], "document"),
    _spec("fetch_url", "read", "Tải nội dung một trang web.", {"url": (STR, "địa chỉ http(s)")}, ["url"], "web"),
    _spec("lookup_order", "read", "Tra cứu đơn hàng hoặc bản ghi theo mã.", {"order_id": (STR, "mã đơn, hoặc 'latest'")},
          ["order_id"], "tool"),
    _spec("lookup_contact", "read", "Tra người nhận đã lưu trong danh bạ của khách theo tên (Mẹ / Mother).",
          {"name": (STR, "tên người nhận đã lưu")}, ["name"], "tool"),
    _spec("transfer_money", "action", "Chuyển tiền từ tài khoản của khách.",
          {"to_account": (STR, "số tài khoản nhận"), "bank_code": (STR, "mã ngân hàng"), "amount": (NUM, "số tiền"),
           "currency": (STR, "mặc định VND")}, ["to_account", "bank_code", "amount"]),
    _spec("refund", "action", "Hoàn tiền một đơn hàng.",
          {"order_id": (STR, "mã đơn"), "amount": (NUM, "số tiền hoàn (USD)"), "order_value": (NUM, "giá trị đơn nếu biết"),
           "reason": (STR, "lý do")}, ["order_id", "amount"]),
    _spec("send_email", "action", "Gửi email.",
          {"to": (STRS, "danh sách người nhận"), "cc": (STRS, "danh sách cc"), "subject": (STR, "tiêu đề"),
           "body": (STR, "nội dung"), "attachments": (STRS, "tên file đính kèm")}, ["to", "subject", "body"]),
    _spec("share_file", "action", "Chia sẻ một file.",
          {"file_id": (STR, "id file"), "share_with": (STRS, "người hoặc miền nhận"), "permission": (STR, "view, comment hoặc edit")},
          ["file_id", "share_with"]),
    _spec("data_access", "action", "Truy xuất dữ liệu.",
          {"resource": (STR, "tên tài nguyên"), "query_scope": (STR, "own_account hoặc all")}, ["resource"]),
    _spec("voucher_apply", "action", "Áp mã giảm giá cho đơn.",
          {"order_id": (STR, "mã đơn"), "order_total": (NUM, "tổng đơn"), "voucher_code": (STR, "mã giảm giá"),
           "discount_percent": (NUM, "phần trăm giảm"), "discount_amount": (NUM, "số tiền giảm")},
          ["order_id", "order_total", "voucher_code"]),
    _spec("password_reset", "action", "Đặt lại mật khẩu cho một tài khoản.",
          {"target_account": (STR, "tài khoản cần đặt lại"), "verification_method": (STR, "cách xác minh"),
           "ticket_id": (STR, "mã ticket nếu có")}, ["target_account", "verification_method"]),
    _spec("account_recovery", "action", "Khôi phục một tài khoản.",
          {"target_account": (STR, "tài khoản cần khôi phục"), "verification_method": (STR, "cách xác minh"),
           "ticket_id": (STR, "mã ticket nếu có")}, ["target_account", "verification_method"]),
    _spec("post_message", "action", "Đăng tin nhắn lên kênh hoặc gửi cho một người.",
          {"target": (STR, "kênh, người nhận hoặc webhook"), "text": (STR, "nội dung")}, ["target", "text"]),
    _spec("http_request", "action", "Gọi một địa chỉ HTTP.",
          {"url": (STR, "địa chỉ http(s)"), "method": (STR, "GET, POST..."), "body": (STR, "nội dung gửi")}, ["url"]),
]}

READ_TOOLS = tuple(n for n, t in TOOLS.items() if t.kind == "read")
ACTION_TOOLS = tuple(n for n, t in TOOLS.items() if t.kind == "action")


def openai_tools(names=None) -> List[Dict[str, Any]]:
    """The tool list in the OpenAI chat format (Groq and Gemini accept it as is)."""
    out = []
    for name in names or TOOLS:
        t = TOOLS[name]
        props = {}
        for pname, (ptype, desc) in t.params.items():
            props[pname] = {"type": ptype, "description": desc}
            if ptype == STRS:
                props[pname]["items"] = {"type": "string"}
        out.append({"type": "function", "function": {
            "name": t.name, "description": t.description,
            "parameters": {"type": "object", "properties": props, "required": list(t.required)}}})
    return out


def check_arguments(name: str, args: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(clean arguments, None) or (None, error text). Unknown arguments (including system fields the model tried to
    set) are dropped; numbers given as text are converted; a string given for a list becomes a one-item list."""
    spec = TOOLS.get(name)
    if spec is None:
        return None, f"unknown tool '{name}'"
    if not isinstance(args, dict):
        return None, "arguments must be an object"
    clean: Dict[str, Any] = {}
    for pname, (ptype, _) in spec.params.items():
        if pname not in args or args[pname] in (None, ""):
            continue
        value = args[pname]
        if ptype == NUM:
            if isinstance(value, bool):
                return None, f"'{pname}' must be a finite number"
            try:
                value = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
            except (TypeError, ValueError):
                return None, f"'{pname}' must be a number"
            if not math.isfinite(value):
                return None, f"'{pname}' must be a finite number"
        elif ptype == STRS:
            value = [str(v) for v in value] if isinstance(value, list) else [str(value)]
        else:
            if isinstance(value, (dict, list)):
                return None, f"'{pname}' must be text"
            value = str(value)
        clean[pname] = value
    missing = [p for p in spec.required if p not in clean]
    if missing:
        return None, "missing argument(s): " + ", ".join(missing)
    return clean, None


def build_payload(name: str, args: Dict[str, Any], identity: Dict[str, Any], backend=None) -> Dict[str, Any]:
    """The payload handed to validate_action: the model's arguments plus the fields the session fixes. Where Layer 4
    needs a value the model may not know (a refund's order_value), the backend record is used, then the amount."""
    payload = dict(args)
    for key in SYSTEM_FIELDS:
        if key in identity:
            payload[key] = identity[key]
    if name == "refund" and "order_value" not in payload:
        known = backend.order_value(payload["order_id"]) if backend is not None else None
        payload["order_value"] = known or payload["amount"]
    return payload
