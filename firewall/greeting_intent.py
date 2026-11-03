"""Recognize whole, bounded greetings on the user channel.

No arbitrary names, quoted content, commands, IDs, URLs or trailing text match.
The orchestrator still runs both detection layers and preserves their raw trace.
"""
import re
import unicodedata


_GREETING = re.compile(
    r"(?:(?:xin )?chào(?: (?:bạn|anh|chị|em|mọi người|trợ lý|bot))?(?: (?:nhé|nha|ạ))?"
    r"|(?:xin )?chao(?: (?:ban|anh|chi|em|moi nguoi|tro ly|bot))?(?: (?:nhe|nha|a))?"
    r"|(?:hello|hi|hey)(?: (?:there|bot|assistant))?"
    r"|good (?:morning|afternoon|evening))"
    r"[.!?]{0,3}"
)


def plain_greeting(text: str) -> bool:
    if len(text) > 80:
        return False
    normalized = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return bool(_GREETING.fullmatch(normalized))
