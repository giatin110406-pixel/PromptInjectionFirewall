"""
Split text into the units Layer 1 embeds and compares: sentences, and bounded pieces of long
sentences.

An injected instruction is usually one sentence inside a long document. Embedding the whole
document dilutes it (one sentence among thirty), so each unit is scored on its own and the text
takes the score of its worst unit. Chat messages are one to three units; a document is up to
`max_units`.
"""
import re
from typing import List

# Bump when `prepare_unit` changes: an index built with another version is refused at load time,
# because its vectors were made from differently prepared text.
PREPARE_VERSION = "1"

_BREAK = re.compile(r"(?<=[.!?…])\s+|\n+")

MAX_UNIT_CHARS = 300   # longer sentences are cut at a word boundary, never truncated
MIN_UNIT_CHARS = 4     # fragments shorter than this carry no meaning
DEFAULT_MAX_UNITS = 64


def _cut_long(sentence: str, limit: int) -> List[str]:
    """Break a very long sentence into pieces of at most `limit` characters at word boundaries."""
    if len(sentence) <= limit:
        return [sentence]
    pieces, current = [], ""
    for word in sentence.split():
        if len(word) > limit:  # an unbroken token (a base64 blob, a URL): split it hard
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(word[i:i + limit] for i in range(0, len(word), limit))
            continue
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


def split_units(text: str, max_units: int = DEFAULT_MAX_UNITS, max_chars: int = MAX_UNIT_CHARS) -> List[str]:
    """
    Sentences of `text`, in order. When there are more than `max_units`, the first 3/4 and the
    last 1/4 of the budget are kept so an instruction hidden at either end is still scored.
    Anything between is skipped: this is the documented blind spot of the cap.
    """
    units: List[str] = []
    for part in _BREAK.split(text):
        part = part.strip()
        if len(part) >= MIN_UNIT_CHARS:
            units.extend(piece for piece in _cut_long(part, max_chars) if len(piece) >= MIN_UNIT_CHARS)
    if len(units) <= max_units:
        return units
    tail = max_units // 4
    return units[: max_units - tail] + units[-tail:]


def was_capped(text: str, max_units: int = DEFAULT_MAX_UNITS, max_chars: int = MAX_UNIT_CHARS) -> bool:
    """True when `split_units` had to skip part of the text."""
    uncapped = split_units(text, max_units=10 ** 9, max_chars=max_chars)
    return len(uncapped) > max_units


# "...bằng tiếng Việt." / "...in English." at the end of a request only says which language to answer
# in. In the training data it ends many attack messages AND many ordinary questions, so to an embedding
# model it looked like a shared attack feature, and a plain "how do I check open ports? answer in
# Vietnamese" landed next to "reveal your instructions in Vietnamese".
_LANGUAGE_REQUEST = re.compile(
    r"[\s,;:\-]*(?:hãy\s+|vui\s+lòng\s+|xin\s+|please\s+)?"
    r"(?:(?:trả\s+lời|viết|giải\s+thích|hướng\s+dẫn|trình\s+bày|phản\s+hồi|answer|reply|respond|write|explain)\s+)?"
    r"(?:bằng|in)\s+(?:tiếng\s+)?(?:việt(?:\s+nam)?|anh|english|vietnamese)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def prepare_unit(text: str) -> str:
    """What the embedder actually reads for one unit: the unit without a trailing language request."""
    stripped = _LANGUAGE_REQUEST.sub("", text).strip()
    return stripped if len(stripped) >= MIN_UNIT_CHARS else text.strip()
