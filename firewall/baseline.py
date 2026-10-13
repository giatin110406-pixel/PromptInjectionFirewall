"""
Baseline Classifier for AI Firewall (Regex-only).
Used as a benchmark baseline to demonstrate performance gains
achieved by ML/DL layers in subsequent phases.
Supports both English and Vietnamese prompt injection patterns.

Design rules for patterns (they run as a hard BLOCK in Layer 1, so a loose
pattern blocks real customers):
- Never join two phrases with an unbounded ".*?". Use a gap bounded to one sentence.
- Write Vietnamese patterns once, with diacritics. Layer 1 derives an
  accent-stripped twin automatically for unaccented input.
- Patterns that are ambiguous in a question ("can I reset my password without
  OTP?") go in SOFT_BASELINE_PATTERNS and are ignored when the sentence is a question.
"""
import re
from typing import Dict, Any, List

# One-sentence gap: no sentence terminator between the two anchors.
_GAP = r"[^.?!\n]{0,40}?"

_IGNORE_NOUN_VI = r"(?:hướng\s+dẫn|chỉ\s+dẫn|chỉ\s+thị|chỉ\s+dặn|lệnh|quy\s+tắc|chính\s+sách|ràng\s+buộc|giới\s+hạn)"
# "phớt lờ mọi hướng dẫn của ngân hàng" tells a person to ignore a bank's rules; it is not an
# instruction to the AI. Only "của bạn / hệ thống / AI / chatbot..." keeps the pattern an attack.
_NOT_A_THIRD_PARTY = r"(?!\s+của\s+(?!bạn|hệ\s+thống|ai\b|mô\s+hình|chatbot|trợ\s+lý))"
_PRIOR_VI =r"(?:trước\s+đó|trước\s+đây|ở\s+trên|ban\s+nãy|ban\s+đầu|của\s+bạn|của\s+hệ\s+thống|hệ\s+thống|an\s+toàn|bảo\s+mật)"

DEFAULT_BASELINE_PATTERNS = [
    # ---------------- English ----------------
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"ignore\s+(?:all|any|every)\s+(?:of\s+)?(?:the\s+)?(?:previous\s+|prior\s+|above\s+|earlier\s+)?(?:instructions|rules|prompts|directions|guidelines)",
    r"ignore\s+(?:the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions|rules|prompts|directions|guidelines)",
    r"(?:disregard|forget|ignore)\s+(?:everything|anything|all)\s+(?:above|before|previously|you\s+(?:were|have\s+been)\s+told)",
    r"disregard\s+(all\s+|prior\s+|system\s+)?(prompts|rules|instructions|constraints)",
    r"(?:disregard|ignore|forget|override|bypass)\s+(?:all\s+)?(?:of\s+)?your\s+(?:earlier\s+|previous\s+|prior\s+|initial\s+|original\s+)?(?:rules|instructions|guidelines|restrictions|constraints|programming)",
    # "system prompt" alone is a topic (people ask how to protect one, or what one is). It is an attack
    # when paired with a verb that asks for it to be shown or overridden, or addressed as "your".
    r"(?:print|reveal|show|display|output|repeat|leak|expose|dump|disclose|share|copy|recite|ignore|override|forget|bypass|tell\s+me|give\s+me|send\s+me)\s+(?:me\s+)?(?:all\s+)?(?:of\s+)?(?:your|the|my|its|this)?\s*(?:initial\s+|original\s+|hidden\s+|full\s+|entire\s+|exact\s+|secret\s+)?system\s+(?:prompt|message|instructions)",
    r"system\s+prompt\s+(?:verbatim|word\s+for\s+word|in\s+full|exactly)",
    r"(?:what\s+(?:is|are)|what's)\s+your\s+(?:initial\s+|original\s+|hidden\s+)?system\s+(?:prompt|message|instructions)",
    # "jailbreak" alone is also a topic (iPhone jailbreak, AI safety); see SOFT_BASELINE_PATTERNS.
    r"jailbreak\s+(?:mode|prompt|this|the\s+(?:ai|model|chatbot|assistant)|your\s+(?:rules|restrictions))",
    r"(?:enable|activate|enter|switch\s+to|use)\s+jailbreak",
    r"you\s+are\s+now\s+(an?\s+)?(unrestricted|dan|developer|root|evil|jailbreak)",
    r"dan\s+mode",
    r"developer\s+debug\s+mode",
    r"developer\s+mode(?!.{0,40}\b(?:android|iphone|ios|phone|chrome|browser|windows|device|usb|settings|app|samsung|xiaomi)\b)",
    r"pretend\s+you\s+(are|have)",
    r"bypass\s+(all\s+)?(safety|security|filters|policy)",
    r"emergency\s+override",
    r"unrestricted\s+ai",
    r"roleplay\s+as",
    r"drop\s+table",
    r"<\s*script\s*>",
    r"cat\s+/etc/passwd",
    r"cat\s+/etc/shadow",
    r"initial\s+configuration\s+and\s+system\s+instructions",
    r"reveal\s+(internal|database|system|hidden)\s+(prompt|secrets|tokens)",

    # ---------------- Other languages (ignore previous instructions) ----------------
    r"ignor(?:ar|a|e|ez|iere|ieren)\s+(?:todas\s+las\s+|todas\s+|toutes\s+les\s+|alle\s+)?(?:las\s+)?(?:instrucciones|instructions|anweisungen)",

    # ---------------- Vietnamese: roleplay and jailbreak ----------------
    r"(?:đóng\s+vai|giả\s+lập|hãy\s+là)\s+(?:như\s+|là\s+)?(?:hacker|dan|ai\s+không\s+giới\s+hạn|kẻ\s+xấu|nhân\s+vật\s+phản\s+diện|root)",
    r"(?:bạn\s+là|từ\s+bây\s+giờ\s+bạn\s+là)\s+(?:dan|ai\s+không\s+bị\s+ràng\s+buộc|unrestricted)",
    r"(?:như\s+)?(?:một\s+)?(?:ai|trợ\s+lý|mô\s+hình)\s+(?:không\s+(?:có\s+)?(?:bất\s+kỳ\s+)?(?:giới\s+hạn|ràng\s+buộc|kiểm\s+duyệt)|tự\s+do\s+hoàn\s+toàn)",

    # ---------------- Vietnamese: privilege override ----------------
    r"(?:kích\s+hoạt|cấp)\s+(?:quyền\s+)?(?:admin|quản\s+trị|root|super\s+admin|tối\s+cao)",
    r"(?:vượt\s+quyền|chiếm\s+quyền)",
    r"(?:kích\s+hoạt|bật|chuyển\s+sang|vào)\s+chế\s+độ\s+(?:nhà\s+phát\s+triển|gỡ\s+lỗi|debug|quản\s+trị|không\s+giới\s+hạn)",
    r"chế\s+độ\s+(?:nhà\s+phát\s+triển|không\s+giới\s+hạn|jailbreak)",
    r"(?:tôi\s+là)\s+(?:kỹ\s+sư\s+trưởng|quản\s+trị\s+viên|giám\s+sát|admin)" + _GAP
    + r"(?:bỏ\s+qua|cấp\s+quyền|in\s+ra|tiết\s+lộ)\s+(?:mọi\s+|tất\s+cả\s+)?(?:quy\s+tắc|xác\s+minh|kiểm\s+tra|hướng\s+dẫn|system|prompt|mật\s+khẩu|quyền)",

    # ---------------- Vietnamese: ignore / bypass rules ----------------
    # Strong determiner ("mọi", "tất cả") or a prior/system qualifier is required so that
    # "bỏ qua phần giới thiệu, đi thẳng vào quy tắc đổi trả" is not an attack.
    r"(?:bỏ\s+qua|quên\s+(?:hết|đi)|phớt\s+lờ|lờ\s+đi|vô\s+hiệu\s+hóa|hủy\s+bỏ)\s+(?:mọi|tất\s+cả|toàn\s+bộ|hết)\s+(?:các\s+)?" + _IGNORE_NOUN_VI + _NOT_A_THIRD_PARTY,
    r"(?:bỏ\s+qua|quên\s+(?:hết|đi)|phớt\s+lờ|lờ\s+đi|vô\s+hiệu\s+hóa|hủy\s+bỏ)\s+(?:các\s+)?" + _IGNORE_NOUN_VI + r"\s+" + _PRIOR_VI,
    r"(?:quên\s+hết|quên\s+đi|phớt\s+lờ|bỏ\s+qua|lờ\s+đi)\s+(?:các\s+|mọi\s+|những\s+)?" + _IGNORE_NOUN_VI + r"\s+(?:đã\s+(?:cho|dặn|được\s+cấp)|trước)",
    r"(?:phớt\s+lờ|bỏ\s+qua|lờ\s+đi|quên)\s+(?:toàn\s+bộ|tất\s+cả|mọi|hết)\s+(?:những\s+gì|điều|thứ|nội\s+dung)\s+(?:đã\s+|được\s+)?(?:dặn|chỉ\s+dẫn|nói|yêu\s+cầu|cho\s+trước|ở\s+trên|trước\s+đó)",
    r"(?:không\s+cần|đừng|không\s+được)\s+(?:phải\s+)?(?:tuân\s+theo|tuân\s+thủ|làm\s+theo)\s+(?:bất\s+kỳ\s+|mọi\s+|các\s+)?(?:quy\s+tắc|chính\s+sách|ràng\s+buộc|hướng\s+dẫn|rule)",
    r"vượt\s+qua\s+(?:bộ\s+lọc|hàng\s+rào\s+bảo\s+vệ|tường\s+lửa\s+(?:của\s+)?(?:bạn|hệ\s+thống)|kiểm\s+duyệt\s+(?:của\s+)?(?:bạn|hệ\s+thống|ai))",

    # ---------------- Vietnamese: system prompt / secret leak ----------------
    r"(?:tiết\s+lộ|hiển\s+thị|in\s+ra|cho\s+tôi\s+biết|cho\s+xem)\s+(?:toàn\s+bộ\s+)?(?:system\s+prompt|hướng\s+dẫn\s+ban\s+đầu|câu\s+lệnh\s+ẩn|chỉ\s+dẫn\s+ẩn|khóa\s+bí\s+mật|api\s+key|token\s+quản\s+trị|pass\s+root|mật\s+khẩu\s+root)",
    r"(?:system\s+prompt\s+ban\s+đầu|system\s+prompt\s+gốc|lời\s+nhắc\s+hệ\s+thống)",
    # A verb that asks to see it, or "system prompt của bạn" (addressed to the AI). "Bảo vệ system
    # prompt của chatbot công ty" names the topic and does not match.
    r"(?:cho\s+(?:tôi|mình|em|anh|chị)\s+xem|xem|đọc|in\s+ra|xuất\s+ra|chép\s+lại|lặp\s+lại|tiết\s+lộ|hiển\s+thị|gửi\s+cho\s+(?:tôi|mình))\s+(?:nguyên\s+văn\s+|toàn\s+bộ\s+)?(?:cái\s+)?system\s+prompt",
    r"system\s+prompt\s+của\s+(?:bạn|mày|em\s+đi|chatbot\s+này|trợ\s+lý\s+này)",
    r"(?:cho\s+(?:tôi|mình)\s+xem|xuất|hiển\s+thị|in\s+ra|tiết\s+lộ|đọc\s+lại|lặp\s+lại|nói\s+cho\s+tôi)\s+.{0,40}?(?:prompt|chỉ\s+dẫn|lời\s+nhắc|câu\s+lệnh)\s+hệ\s+thống",
    r"(?:giả\s+lập|đóng\s+vai)" + _GAP + r"(?:hacker|không\s+kiểm\s+duyệt)",
]

# Ambiguous when phrased as a question; exempted by Layer 1 when the matching sentence
# is a question ("?" or "... có được không").
SOFT_BASELINE_PATTERNS = [
    r"jailbreak",  # a topic as often as an attack: exempt when the sentence asks or explains (see Layer 1)
    # A sensitive action together with an explicit request to skip its safeguard. Without the second
    # half the sentence is an ordinary customer request ("please refund my order"), which Layer 1 must
    # not block. As a question ("can I reset it without the OTP?") it is exempt.
    r"\b(?:refund|transfer|wire|withdraw|delete|reset|approve|grant|issue|send)\b[^.?!\n]{0,60}\b(?:skip|bypass|without|no\s+need\s+for|don'?t\s+ask\s+for|do\s+not\s+ask\s+for)\s+(?:the\s+|any\s+|a\s+)?(?:otp|approval|verification|manager|confirmation|authentication|2fa|checks?|review)",
    r"(?:hoàn\s+(?:tiền|ngay|lại)|chuyển\s+(?:khoản|tiền)|rút\s+tiền|xóa|đặt\s+lại\s+mật\s+khẩu|đổi\s+mật\s+khẩu|cấp\s+quyền|duyệt|phát\s+hành)" + _GAP + r"(?:bỏ\s+qua|không\s+cần|khỏi\s+cần|đừng\s+hỏi|mà\s+không\s+cần|miễn)\s+(?:bước\s+|việc\s+|cả\s+)?(?:phê\s+duyệt|duyệt|xác\s+nhận|xác\s+minh|xác\s+thực|otp|kiểm\s+tra|ký\s+duyệt|ý\s+kiến\s+quản\s+lý)",
    r"(?:tình\s+huống\s+khẩn\s+cấp|trường\s+hợp\s+khẩn\s+cấp)" + _GAP + r"(?:bỏ\s+qua|thực\s+thi\s+ngay|không\s+cần\s+kiểm\s+tra)",
    r"khẩn\s+cấp\s*:\s*(?:hoàn\s+tiền|chuyển\s+tiền|cấp\s+quyền|đổi\s+mật\s+khẩu)\s+ngay",
    r"hoàn\s+tiền" + _GAP + r"(?:không\s+cần\s+duyệt|bỏ\s+qua\s+xác\s+nhận|tự\s+động\s+100%)",
    r"(?:đổi\s+mật\s+khẩu|reset\s+pass)" + _GAP + r"(?:không\s+cần\s+otp|bỏ\s+qua\s+xác\s+minh)",
    r"áp\s+dụng\s+mã\s+giảm\s+giá\s+100%" + _GAP + r"(?:không\s+giới\s+hạn|bỏ\s+qua)",
]

# Suspicious, not conclusive: these send the text to Layer 2 (ESCALATE) instead of blocking it.
# Text that addresses "the assistant" and then tells it to drop, replace or leak something is the
# typical shape of an instruction hidden in a document, but a user can also write "Assistant, please
# do not use bullet points". Layer 1 does not know whether the text came from a user or from an
# untrusted document, so it must not block on this alone.
ESCALATE_HINT_PATTERNS = [
    r"\b(?:assistant|ai|chatbot|llm|model)\s*[,:]\s*(?:please\s+)?(?:ignore|disregard|forget|stop|do\s+not|don'?t|instead|you\s+must|you\s+should\s+now)\b",
    r"\b(?:note|message|instruction|notice|attention)s?\s+(?:to|for)\s+(?:the\s+|any\s+)?(?:ai\s+)?(?:assistant|model|llm|chatbot|ai)\b",
    r"\b(?:assistant|chatbot|llm)\s*[,:]?\s+(?:please\s+)?(?:send|forward|email|upload|post)\s+(?:all|the\s+(?:entire|full|whole)|every)\b",
    r"(?:trợ\s+lý(?:\s+ai)?|chatbot)\s*[,:]?\s+(?:hãy\s+)?(?:bỏ\s+qua|quên|phớt\s+lờ|đừng|thay\s+vào\s+đó)",
    r"(?:trợ\s+lý(?:\s+ai)?|chatbot)\s*[,:]?\s+(?:hãy\s+)?(?:gửi|chuyển|chuyển\s+tiếp)\s+(?:toàn\s+bộ|tất\s+cả|mọi)",
    r"(?:lưu\s+ý|ghi\s+chú|thông\s+báo|chỉ\s+thị)\s+(?:dành\s+)?(?:cho|tới|đến)\s+(?:trợ\s+lý|chatbot|ai)\b",
]

ALL_BASELINE_PATTERNS = DEFAULT_BASELINE_PATTERNS + SOFT_BASELINE_PATTERNS


class RegexBaseline:
    def __init__(self, patterns: List[str] = None):
        self.raw_patterns = patterns or DEFAULT_BASELINE_PATTERNS
        self.compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.raw_patterns
        ]

    def predict(self, text: str) -> Dict[str, Any]:
        """
        Classifies input text using regular expressions.
        Returns:
            dict: {
                "is_attack": bool,
                "decision": "BLOCK" | "ALLOW",
                "matched_pattern": str | None,
                "confidence": float
            }
        """
        if not text or not isinstance(text, str):
            return {
                "is_attack": False,
                "decision": "ALLOW",
                "matched_pattern": None,
                "confidence": 0.0
            }

        for pattern in self.compiled_patterns:
            match = pattern.search(text)
            if match:
                return {
                    "is_attack": True,
                    "decision": "BLOCK",
                    "matched_pattern": pattern.pattern,
                    "confidence": 1.0
                }

        return {
            "is_attack": False,
            "decision": "ALLOW",
            "matched_pattern": None,
            "confidence": 0.0
        }
