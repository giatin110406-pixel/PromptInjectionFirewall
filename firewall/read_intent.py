"""A bounded grammar for plain requests to read the latest resource.

Only whole user messages match: no resource names, quoted text, destinations,
URLs, numbers or arbitrary suffixes. This corrects a known L2 false positive
without exempting external content or changing the classifier's threshold.
L1, model availability, conversation risk and action validation still apply.
"""
import re
import unicodedata


_RESOURCE = r"(?:email|thư|tài liệu|trang web|tin nhắn|hóa đơn|ticket)"
_VI = re.compile(
    rf"(?:bạn |hãy |bạn hãy )?(?:xem|đọc|mở|kiểm tra|tóm tắt)(?: giúp)? "
    rf"{_RESOURCE}(?: mới nhất)?(?: của (?:mình|tôi))?"
    r"(?:(?: và| rồi) (?:xử lý|giúp (?:mình|tôi) xử lý))?"
    r"(?: giúp (?:mình|tôi))?(?: nhé| nha)?[.!?]?"
)
_EN = re.compile(
    r"(?:please )?(?:read|open|check|summarize) (?:my |the )?(?:latest )?"
    r"(?:email|message|document|web page|invoice|ticket)"
    r"(?: and (?:handle|summarize) it)?(?: for me)?[.!?]?"
)


def plain_read_request(text: str) -> bool:
    normalized = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return bool(_VI.fullmatch(normalized) or _EN.fullmatch(normalized))
