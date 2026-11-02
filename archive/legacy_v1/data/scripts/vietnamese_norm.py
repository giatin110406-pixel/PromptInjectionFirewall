"""
Vietnamese and Multilingual Text Normalization and Preprocessing Utilities.

Provides:
- Unicode NFC normalization
- Accent removal (tiếng Việt không dấu)
- Teencode / slang dictionary mapping
- Language detection heuristic (vi, en, mixed)
- DataFrame deduplication and label conflict resolution
"""
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
import pandas as pd

TEENCODE_DICT: Dict[str, str] = {
    "ko": "không",
    "k": "không",
    "kg": "không",
    "khong": "không",
    "hok": "không",
    "hổng": "không",
    "hem": "không",
    "hong": "không",
    "dc": "được",
    "đc": "được",
    "duoc": "được",
    "mk": "mật khẩu",
    "mat khau": "mật khẩu",
    "tk": "tài khoản",
    "tai khoan": "tài khoản",
    "acc": "tài khoản",
    "ad": "quản trị viên",
    "adm": "quản trị viên",
    "admin": "quản trị viên",
    "pass": "mật khẩu",
    "passwd": "mật khẩu",
    "pwd": "mật khẩu",
    "pw": "mật khẩu",
    "tks": "cảm ơn",
    "ty": "cảm ơn",
    "thx": "cảm ơn",
    "cam on": "cảm ơn",
    "ng": "người",
    "nguoi": "người",
    "ntn": "như thế nào",
    "bthg": "bình thường",
    "bt": "bình thường",
    "mn": "mọi người",
    "ib": "nhắn tin",
    "inbox": "nhắn tin",
    "cx": "cũng",
    "cung": "cũng",
    "lm": "làm",
    "lam": "làm",
    "vs": "với",
    "voi": "với",
    "s": "sao",
    "trc": "trước",
    "truoc": "trước",
    "h": "giờ",
    "wa": "quá",
    "wá": "quá",
    "nv": "nhân viên",
    "dv": "dịch vụ",
    "kh": "khách hàng",
    "stk": "số tài khoản",
    "chk": "chuyển khoản",
    "otp": "mã xác thực",
    "j": "gì",
    "gi": "gì",
    "bo qua": "bỏ qua",
    "vuot quyen": "vượt quyền",
    "he thong": "hệ thống",
    "quy tac": "quy tắc",
}

VIETNAMESE_ACCENT_MAP = {
    'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
    'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
    'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
    'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
    'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
    'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
    'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
    'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
    'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
    'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
    'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
    'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
    'đ': 'd',
    'À': 'A', 'Á': 'A', 'Ả': 'A', 'Ã': 'A', 'Ạ': 'A',
    'Ă': 'A', 'Ằ': 'A', 'Ắ': 'A', 'Ẳ': 'A', 'Ẵ': 'A', 'Ặ': 'A',
    'Â': 'A', 'Ầ': 'A', 'Ấ': 'A', 'Ẩ': 'A', 'Ẫ': 'A', 'Ậ': 'A',
    'È': 'E', 'É': 'E', 'Ẻ': 'E', 'Ẽ': 'E', 'Ẹ': 'E',
    'Ê': 'E', 'Ề': 'E', 'Ế': 'E', 'Ể': 'E', 'Ễ': 'E', 'Ệ': 'E',
    'Ì': 'I', 'Í': 'I', 'Ỉ': 'I', 'Ĩ': 'I', 'Ị': 'I',
    'Ò': 'O', 'Ó': 'O', 'Ỏ': 'O', 'Õ': 'O', 'Ọ': 'O',
    'Ô': 'O', 'Ồ': 'O', 'Ố': 'O', 'Ổ': 'O', 'Ỗ': 'O', 'Ộ': 'O',
    'Ơ': 'O', 'Ờ': 'O', 'Ớ': 'O', 'Ở': 'O', 'Ỡ': 'O', 'Ợ': 'O',
    'Ù': 'U', 'Ú': 'U', 'Ủ': 'U', 'Ũ': 'U', 'Ụ': 'U',
    'Ư': 'U', 'Ừ': 'U', 'Ứ': 'U', 'Ử': 'U', 'Ữ': 'U', 'Ự': 'U',
    'Ỳ': 'Y', 'Ý': 'Y', 'Ỷ': 'Y', 'Ỹ': 'Y', 'Ỵ': 'Y',
    'Đ': 'D'
}

VIETNAMESE_STOPWORDS = {
    "là", "và", "của", "cho", "có", "trong", "được", "với", "không", "các",
    "những", "này", "khi", "để", "về", "người", "như", "một", "tôi", "bạn",
    "chúng", "họ", "đã", "đang", "sẽ", "phải", "lại", "cũng", "thì", "mà",
    "tại", "từ", "theo", "nếu", "bởi", "vì", "vào", "ra", "lên", "xuống",
    "hệ", "thống", "lệnh", "chỉ", "dẫn", "bỏ", "qua", "quy", "tắc", "khỏi",
    "bảo", "vệ", "cách", "làm", "thế", "nào"
}


def normalize_unicode(text: str) -> str:
    """Normalize text using Unicode NFC form."""
    if not text or not isinstance(text, str):
        return ""
    return unicodedata.normalize("NFC", text)


def remove_vietnamese_accents(text: str) -> str:
    """Convert accented Vietnamese characters to their ASCII / unaccented equivalents."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    result = []
    for ch in normalized:
        result.append(VIETNAMESE_ACCENT_MAP.get(ch, ch))
    return "".join(result)


def expand_teencode(text: str) -> str:
    """Expand teencode and internet slang tokens to standard Vietnamese words."""
    if not text:
        return ""

    tokens = re.split(r"(\s+|[^\w\s])", text)
    expanded = []
    for token in tokens:
        lower_token = token.lower()
        if lower_token in TEENCODE_DICT:
            standard = TEENCODE_DICT[lower_token]
            if token.isupper():
                expanded.append(standard.upper())
            elif token.istitle():
                expanded.append(standard.capitalize())
            else:
                expanded.append(standard)
        else:
            expanded.append(token)
    return "".join(expanded)


def clean_text(text: str, expand_slang: bool = True) -> str:
    """
    Standard clean:
    - NFC normalization
    - Strip excessive whitespaces / tabs
    - Optionally expand teencode
    """
    if not text or not isinstance(text, str):
        return ""
    norm = normalize_unicode(text)
    if expand_slang:
        norm = expand_teencode(norm)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in norm.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def detect_language(text: str) -> str:
    """
    Heuristic language detection returning 'vi', 'en', or 'mixed'.
    Correctly recognizes technical terms in Vietnamese sentences.
    """
    if not text or not isinstance(text, str):
        return "en"

    # Count Vietnamese-specific characters
    vi_special_chars = sum(1 for c in text if c in VIETNAMESE_ACCENT_MAP and c not in "AaEeIiOoUuYyDd")
    words = re.findall(r"\w+", text.lower())
    total_words = len(words)
    if total_words == 0:
        return "en"

    vi_stopwords_hit = sum(1 for w in words if w in VIETNAMESE_STOPWORDS)
    has_vi_signal = vi_special_chars >= 2 or vi_stopwords_hit >= 2

    # Major English instructional/phrasal words
    en_phrase_words = sum(1 for w in words if w in {
        "the", "is", "are", "and", "ignore", "previous", "instructions", "disregard",
        "rules", "system", "prompt", "you", "now", "unrestricted", "assistant", "bypass"
    })

    if has_vi_signal and en_phrase_words >= 3:
        return "mixed"
    elif has_vi_signal:
        return "vi"
    elif en_phrase_words > 0 or total_words >= 2:
        return "en"
    return "en"


def deduplicate_and_resolve_conflicts(
    frame: pd.DataFrame,
    text_column: str = "text",
    label_column: str = "label_binary"
) -> pd.DataFrame:
    """
    Deduplicates prompts while handling conflicting labels:
    - If identical normalized texts have conflicting labels (e.g. both 0 and 1), drop them as ambiguous.
    - Preserves unique rows based on cleaned text.
    """
    if frame.empty:
        return frame

    df = frame.copy()
    df["_norm_key"] = df[text_column].astype(str).str.strip().str.lower()
    df = df[df["_norm_key"].str.len() >= 3]

    label_nunique = df.groupby("_norm_key")[label_column].nunique()
    conflict_keys = set(label_nunique[label_nunique > 1].index)
    if conflict_keys:
        print(f"[WARN] Dropping {len(conflict_keys)} prompts due to conflicting labels across sources.")
        df = df[~df["_norm_key"].isin(conflict_keys)]

    df = df.drop_duplicates(subset=["_norm_key"]).drop(columns=["_norm_key"]).reset_index(drop=True)
    return df
