"""
Feature Engineering Module for Layer 2 XGBoost Classifier.
Extracts syntactic, structural, and semantic features from input prompts,
with full multilingual support for English and Vietnamese attack patterns.
"""
import re
from typing import Dict, Any, List, Optional
import numpy as np
from data.scripts.vietnamese_norm import VIETNAMESE_ACCENT_MAP, VIETNAMESE_STOPWORDS

# English Keywords and Regex patterns
ROLE_CLAIM_PATTERN = re.compile(
    r"\b(i\s+am|i'm|as\s+(an?|the)?\s*([a-z0-9_-]+\s+)?(administrator|admin|system|root|developer|auditor|officer|supervisor)|you\s+are\s+now|pretend|act\s+as|roleplay)\b",
    re.IGNORECASE
)
URGENCY_PATTERN = re.compile(
    r"\b(immediately|urgent|urgently|now|critical|emergency|priority\s*0|execute|asap)\b",
    re.IGNORECASE
)
OVERRIDE_PATTERN = re.compile(
    r"\b(ignore|disregard|bypass|forget|override|unrestricted|disable|lift|suspend)\b",
    re.IGNORECASE
)
PROMPT_LEAK_PATTERN = re.compile(
    r"\b(system\s+prompt|initial\s+instructions|system\s+instructions|secret\s+key|password|hidden\s+prompt|admin\s+token)\b",
    re.IGNORECASE
)
REFUND_PATTERN = re.compile(
    r"\b(refund|chargeback|compensation|order\s+value|exceed|credit|\$|\bamount\b)\b",
    re.IGNORECASE
)
SQL_PATTERN = re.compile(
    r"\b(select|drop|table|union|insert|delete|update|exec|where|or\s+1=1|--)\b",
    re.IGNORECASE
)
DELIMITER_PATTERN = re.compile(
    r"(system:|user:|assistant:|<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\])",
    re.IGNORECASE
)
CODE_PATTERN = re.compile(
    r"(```|<script|<\?php|bash|python|function|def\s+|curl\s+)",
    re.IGNORECASE
)
LIST_PATTERN = re.compile(
    r"\b(step\s*\d|first,|second,|1\.|2\.|3\.)",
    re.IGNORECASE
)

# Vietnamese Keywords and Regex patterns
VI_ROLE_CLAIM_PATTERN = re.compile(
    r"(tôi\s+là|toi\s+la|đóng\s+vai|dong\s+vai|giả\s+lập|gia\s+lap|hãy\s+là|hay\s+la|"
    r"kỹ\s+sư\s+trưởng|ky\s+su\s+truong|quản\s+trị\s+viên|quan\s+tri\s+vien|giám\s+sát\s+viên|"
    r"chuyên\s+gia\s+bảo\s+mật|nhân\s+vật\s+phản\s+diện|hacker|root|admin)",
    re.IGNORECASE
)
VI_URGENCY_PATTERN = re.compile(
    r"(khẩn\s+cấp|khan\s+cap|ngay\s+lập\s+tức|ngay\s+lap\s+tuc|ngay\s+bây\s+giờ|ngay\s+bay\s+gio|"
    r"gấp|lập\s+tức|lap\s+tuc|nhanh\s+lên|ngay\s+và\s+luôn|hỏa\s+tốc)",
    re.IGNORECASE
)
VI_PRIVILEGE_OVERRIDE_PATTERN = re.compile(
    r"(bỏ\s+qua|bo\s+qua|vượt\s+quyền|vuot\s+quyen|cấp\s+quyền|cap\s+quyen|quên\s+đi|quen\s+di|"
    r"không\s+cần\s+tuân|khong\s+can\s+tuan|vô\s+hiệu\s+hóa|vo\s+hieu\s+hoa|vượt\s+qua\s+bộ\s+lọc|"
    r"toàn\s+quyền|quyền\s+root|quyền\s+admin|toan\s+quyen|chế\s+độ\s+nhà\s+phát\s+triển)",
    re.IGNORECASE
)
VI_PROMPT_LEAK_PATTERN = re.compile(
    r"(system\s+prompt|hướng\s+dẫn\s+ban\s+đầu|huong\s+dan\s+ban\s+dau|chỉ\s+dẫn\s+gốc|"
    r"câu\s+lệnh\s+ẩn|cau\s+lenh\s+an|khóa\s+bí\s+mật|khoa\s+bi\s+mat|tiết\s+lộ|tiet\s+lo|"
    r"in\s+ra\s+system|hiển\s+thị\s+lời\s+nhắc|lời\s+nhắc\s+gốc)",
    re.IGNORECASE
)
VI_ACTION_ABUSE_PATTERN = re.compile(
    r"(bỏ\s+qua|bo\s+qua|không\s+cần|khong\s+can|ko\s+can|k\s+can|tự\s+động|tu\s+dong|100%|ngay\s+lập\s+tức|vượt\s+quyền)"
    r".*?(hoàn\s+tiền|hoan\s+tien|chuyển\s+tiền|chuyen\s+tien|mã\s+giảm\s+giá|ma\s+giam\s+gia|đổi\s+mật\s+khẩu|reset\s+pass)"
    r"|(hoàn\s+tiền|hoan\s+tien|chuyển\s+tiền|chuyen\s+tien|đổi\s+mật\s+khẩu|reset\s+pass)"
    r".*?(bỏ\s+qua|bo\s+qua|không\s+cần|khong\s+can|ko\s+can|k\s+can|tự\s+động|100%|ngay\s+lập\s+tức|vượt\s+quyền)",
    re.IGNORECASE
)
TEENCODE_PATTERN = re.compile(
    r"\b(ko|k|kg|hok|hổng|hem|dc|đc|duoc|mk|tk|acc|ad|adm|pass|pwd|pw|tks|ty|thx|ng|ntn|bthg|bt|mn|ib|cx|lm|vs|stk|chk|otp)\b",
    re.IGNORECASE
)

FEATURE_NAMES = [
    # Baseline 25 Features
    "token_count",
    "char_count",
    "avg_word_length",
    "capital_ratio",
    "special_char_count",
    "punctuation_ratio",
    "digit_count",
    "newline_count",
    "has_numbered_list",
    "has_bullet_list",
    "has_code_block",
    "has_delimiter_injection",
    "sql_keyword_count",
    "has_url_or_path",
    "has_base64_cue",
    "role_claim_count",
    "urgency_word_count",
    "override_word_count",
    "prompt_leak_cue_count",
    "refund_word_count",
    "question_mark_count",
    "exclamation_mark_count",
    "max_similarity",
    "letter_ratio",
    "space_ratio",
    # Vietnamese & Multilingual Engineered Features
    "vietnamese_token_count",
    "vietnamese_role_claim_count",
    "teencode_count",
    "urgency_phrase_count_vi",
    "privilege_phrase_count_vi",
    "vietnamese_prompt_leak_count",
    "vietnamese_action_abuse_count",
]


def extract_features(text: str, top_similarity: float = 0.0) -> Dict[str, float]:
    """
    Extract a dictionary of numerical features from the text.
    Supports both international and Vietnamese prompt characteristics.
    """
    if not text or not isinstance(text, str):
        text = ""

    text_len = max(len(text), 1)
    tokens = text.split()
    token_count = len(tokens)

    # 1-8: Syntactic Features
    char_count = len(text)
    avg_word_length = sum(len(t) for t in tokens) / max(token_count, 1)
    capital_ratio = sum(1 for c in text if c.isupper()) / text_len
    special_chars = len(re.findall(r"[(){}\[\]<>'\"`$%^&*~|\\;]", text))
    punct_count = len(re.findall(r"[,.;:!?\-]", text))
    punctuation_ratio = punct_count / text_len
    digit_count = sum(1 for c in text if c.isdigit())
    newline_count = text.count("\n")

    # 9-15: Structural Features
    has_numbered_list = 1.0 if LIST_PATTERN.search(text) else 0.0
    has_bullet_list = 1.0 if re.search(r"^\s*[-*•]\s+", text, re.MULTILINE) else 0.0
    has_code_block = 1.0 if CODE_PATTERN.search(text) else 0.0
    has_delimiter_injection = 1.0 if DELIMITER_PATTERN.search(text) else 0.0
    sql_keyword_count = float(len(SQL_PATTERN.findall(text)))
    has_url_or_path = 1.0 if re.search(r"(https?://|/etc/|C:\\|[a-z0-9_-]+\.[a-z]{2,4}/)", text, re.IGNORECASE) else 0.0
    has_base64_cue = 1.0 if re.search(r"(base64|decode|eval\()", text, re.IGNORECASE) else 0.0

    # 16-22: Semantic / Intent Keyword Features (English)
    role_claim_count = float(len(ROLE_CLAIM_PATTERN.findall(text)))
    urgency_word_count = float(len(URGENCY_PATTERN.findall(text)))
    override_word_count = float(len(OVERRIDE_PATTERN.findall(text)))
    prompt_leak_cue_count = float(len(PROMPT_LEAK_PATTERN.findall(text)))
    refund_word_count = float(len(REFUND_PATTERN.findall(text)))
    question_mark_count = float(text.count("?"))
    exclamation_mark_count = float(text.count("!"))

    # 23-25: Representation & Ratios
    letter_ratio = sum(1 for c in text if c.isalpha()) / text_len
    space_ratio = text.count(" ") / text_len

    # Vietnamese & Multilingual Features
    # Count tokens that contain Vietnamese accented characters or stopwords
    vi_token_matches = sum(
        1 for t in tokens if any(c in VIETNAMESE_ACCENT_MAP for c in t) or t.lower() in VIETNAMESE_STOPWORDS
    )
    vietnamese_token_count = float(vi_token_matches)
    vietnamese_role_claim_count = float(len(VI_ROLE_CLAIM_PATTERN.findall(text)))
    teencode_count = float(len(TEENCODE_PATTERN.findall(text)))
    urgency_phrase_count_vi = float(len(VI_URGENCY_PATTERN.findall(text)))
    privilege_phrase_count_vi = float(len(VI_PRIVILEGE_OVERRIDE_PATTERN.findall(text)))
    vietnamese_prompt_leak_count = float(len(VI_PROMPT_LEAK_PATTERN.findall(text)))
    vietnamese_action_abuse_count = float(len(VI_ACTION_ABUSE_PATTERN.findall(text)))

    features = {
        "token_count": float(token_count),
        "char_count": float(char_count),
        "avg_word_length": float(round(avg_word_length, 4)),
        "capital_ratio": float(round(capital_ratio, 4)),
        "special_char_count": float(special_chars),
        "punctuation_ratio": float(round(punctuation_ratio, 4)),
        "digit_count": float(digit_count),
        "newline_count": float(newline_count),
        "has_numbered_list": has_numbered_list,
        "has_bullet_list": has_bullet_list,
        "has_code_block": has_code_block,
        "has_delimiter_injection": has_delimiter_injection,
        "sql_keyword_count": sql_keyword_count,
        "has_url_or_path": has_url_or_path,
        "has_base64_cue": has_base64_cue,
        "role_claim_count": role_claim_count,
        "urgency_word_count": urgency_word_count,
        "override_word_count": override_word_count,
        "prompt_leak_cue_count": prompt_leak_cue_count,
        "refund_word_count": refund_word_count,
        "question_mark_count": question_mark_count,
        "exclamation_mark_count": exclamation_mark_count,
        "max_similarity": float(top_similarity),
        "letter_ratio": float(round(letter_ratio, 4)),
        "space_ratio": float(round(space_ratio, 4)),
        # Vietnamese & Multilingual additions
        "vietnamese_token_count": vietnamese_token_count,
        "vietnamese_role_claim_count": vietnamese_role_claim_count,
        "teencode_count": teencode_count,
        "urgency_phrase_count_vi": urgency_phrase_count_vi,
        "privilege_phrase_count_vi": privilege_phrase_count_vi,
        "vietnamese_prompt_leak_count": vietnamese_prompt_leak_count,
        "vietnamese_action_abuse_count": vietnamese_action_abuse_count,
    }

    return features


def extract_feature_vector(text: str, top_similarity: float = 0.0) -> List[float]:
    """Returns extracted features ordered as a float vector according to FEATURE_NAMES."""
    feat_dict = extract_features(text, top_similarity)
    return [feat_dict[k] for k in FEATURE_NAMES]
