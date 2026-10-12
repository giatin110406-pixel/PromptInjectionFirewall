"""
Baseline Classifier for AI Firewall (Regex-only).
Used as a benchmark baseline to demonstrate performance gains
achieved by ML/DL layers in subsequent phases.
Supports both English and Vietnamese prompt injection patterns.
"""
import re
from typing import Dict, Any, List

DEFAULT_BASELINE_PATTERNS = [
    # English Patterns
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"disregard\s+(all\s+|prior\s+|system\s+)?(prompts|rules|instructions|constraints)",
    r"system\s+prompt",
    r"you\s+are\s+now\s+(an?\s+)?(unrestricted|dan|developer|root|evil|jailbreak)",
    r"dan\s+mode",
    r"developer\s+debug\s+mode",
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

    # Vietnamese Patterns (Roleplay & Jailbreak)
    r"(đóng\s+vai|dong\s+vai|giả\s+lập|gia\s+lap|hãy\s+là|hay\s+la)\s+(như\s+|là\s+)?(hacker|dan|ai\s+không\s+giới\s+hạn|ai\s+khong\s+gioi\s+han|kẻ\s+xấu|nhân\s+vật\s+phản\s+diện|root)",
    r"(bạn\s+là|ban\s+la|từ\s+bây\s+giờ\s+bạn\s+là|tu\s+bay\s+gio\s+ban\s+la)\s+(dan|ai\s+không\s+bị\s+ràng\s+buộc|unrestricted)",
    
    # Vietnamese Admin & Privilege Override
    r"(kích\s+hoạt|kich\s+hoat|cấp|cap)\s+(quyền\s+)?(admin|quản\s+trị|quan\s+tri|root|super\s+admin|tối\s+cao)",
    r"(tôi\s+là|toi\s+la)\s+(kỹ\s+sư\s+trưởng|ky\s+su\s+truong|quản\s+trị\s+viên|quan\s+tri\s+vien|giám\s+sát|giam\s+sat|admin).*?(bỏ\s+qua|bo\s+qua|cấp\s+quyền|cap\s+quyen|in\s+ra|tiết\s+lộ)",
    r"(vượt\s+quyền|vuot\s+quyen|chiếm\s+quyền|chiem\s+quyen)",
    r"chế\s+độ\s+(nhà\s+phát\s+triển|nha\s+phat\s+trien|bảo\s+trì|bao\s+tri|gỡ\s+lỗi|debug)",

    # Vietnamese Ignore / Bypass Rules (Accented and Unaccented / Teencode)
    r"(bỏ\s+qua|bo\s+qua|quên\s+đi|quen\s+di)\s+(tất\s+cả\s+|toàn\s+bộ\s+|mọi\s+|tat\s+ca\s+)?(hướng\s+dẫn|huong\s+dan|chỉ\s+dẫn|chi\s+dan|quy\s+tắc|quy\s+tac|chính\s+sách|chinh\s+sach|ràng\s+buộc|rang\s+buoc|lệnh|lenh)",
    r"(không\s+cần|khong\s+can|ko\s+can|k\s+can|ko\s+tuan|k\s+tuan)\s+(tuân\s+theo|tuan\s+theo|tuân\s+thủ|tuan\s+thu|theo)?\s*(quy\s+tắc|quy\s+tac|chính\s+sách|chinh\s+sach|chế\s+độ|che\s+do|an\s+toàn|an\s+toan|bảo\s+mật|bao\s+mat|rule)",
    r"vượt\s+qua\s+(bộ\s+lọc|kiểm\s+duyệt|tường\s+lửa|hàng\s+rào\s+bảo\s+vệ)",

    # Vietnamese Urgency Bypass
    r"(tình\s+huống\s+khẩn\s+cấp|tinh\s+huong\s+khan\s+cap|trường\s+hợp\s+khẩn\s+cấp).*?(bỏ\s+qua|thực\s+thi\s+ngay|không\s+cần\s+kiểm\s+tra)",
    r"(khẩn\s+cấp|khan\s+cap)\s*:\s*(hoàn\s+tiền|chuyển\s+tiền|cấp\s+quyền|đổi\s+mật\s+khẩu)\s+ngay",

    # Vietnamese System Prompt / Secret Leak
    r"(tiết\s+lộ|tiet\s+lo|hiển\s+thị|hien\s+thi|in\s+ra|cho\s+tôi\s+biết|cho\s+toi\s+biet|cho\s+xem)\s+(toàn\s+bộ\s+)?(system\s+prompt|hướng\s+dẫn\s+ban\s+đầu|huong\s+dan\s+ban\s+dau|câu\s+lệnh\s+ẩn|chỉ\s+dẫn\s+ẩn|khóa\s+bí\s+mật|api\s+key|token\s+quản\s+trị|pass\s+root|mật\s+khẩu\s+root|mat\s+khau\s+root)",
    r"(system\s+prompt\s+ban\s+đầu|system\s+prompt\s+gốc|lời\s+nhắc\s+hệ\s+thống)",

    # Vietnamese Financial / Account Abuse Cues
    r"(hoàn\s+tiền|hoan\s+tien)\s+.*?(không\s+cần\s+duyệt|khong\s+can\s+duyet|bỏ\s+qua\s+xác\s+nhận|tự\s+động\s+100%)",
    r"(đổi\s+mật\s+khẩu|doi\s+mat\s+khau|reset\s+pass).*?(không\s+cần\s+otp|khong\s+can\s+otp|bỏ\s+qua\s+xác\s+minh|ko\s+can\s+mk)",
    r"(áp\s+dụng|ap\s+dung)\s+mã\s+giảm\s+giá\s+100%\s+.*?(không\s+giới\s+hạn|bỏ\s+qua)",
]

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
