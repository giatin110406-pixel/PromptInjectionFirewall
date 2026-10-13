"""
L0 Normalize: build the text "views" that the signature layer inspects.

Attackers evade regexes with invisible characters, look-alike letters, inserted
separators ("B.ỏ q.ua"), teencode, dropped diacritics, or by encoding the payload
(base64, %xx). Each view undoes one of these tricks. The original text is never
modified: views are used for matching only.
"""
import base64
import binascii
import re
import unicodedata
from typing import List, Tuple
from urllib.parse import unquote

from data.scripts.vietnamese_norm import clean_text, remove_vietnamese_accents

_INVISIBLE = dict.fromkeys(
    map(ord, "​‌‍‎‏⁠⁡⁢⁣⁤﻿­᠎"),
    None,
)

# Cyrillic/Greek letters that render like Latin ones.
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X", "І": "I",
    "ο": "o", "α": "a", "ε": "e", "ν": "v", "ι": "i",
})

_SEPARATOR_BETWEEN_LETTERS = re.compile(r"(?<=\w)[.\-_*·•|/\\](?=\w)")
_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")

# Leetspeak: digits and symbols standing in for letters ("1gn0re", "b0 qu4", "5ystem").
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
_LEET_CHARS = set("013457@$!")
_TOKEN = re.compile(r"\S+")
ACCENT_FREE_VIEWS = ("unaccented", "leet")


def strip_invisible(text: str) -> str:
    """NFKC-normalize, drop zero-width/soft-hyphen characters, fold homoglyphs."""
    return unicodedata.normalize("NFKC", text).translate(_INVISIBLE).translate(_HOMOGLYPHS)


def collapse_separators(text: str) -> str:
    """Remove punctuation inserted inside words: 'b.ỏ q.ua' -> 'bỏ qua'."""
    return _SEPARATOR_BETWEEN_LETTERS.sub("", text)


def decode_leetspeak(text: str) -> str:
    """
    Map look-alike digits/symbols to letters, but only inside tokens that already contain a
    letter. Pure numbers ("order 12345", "256", "$20") are left alone, so prices and ids do not
    turn into words. The result is a matching view only; the original text is never changed.
    """
    def fix(match: "re.Match[str]") -> str:
        token = match.group(0)
        letters = sum(c.isalpha() for c in token)
        leet = sum(c in _LEET_CHARS for c in token)
        if letters >= 1 and leet >= 1:
            return token.translate(_LEET)
        return token

    return _TOKEN.sub(fix, text)


def _decoded_payloads(text: str) -> List[str]:
    """Best-effort decode of percent-encoding and base64 tokens into readable text."""
    payloads: List[str] = []
    if "%" in text:
        unquoted = unquote(text)
        if unquoted != text:
            payloads.append(unquoted)
    for token in _BASE64_TOKEN.findall(text):
        padded = token + "=" * (-len(token) % 4)
        try:
            decoded = base64.b64decode(padded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded and decoded.isprintable():
            payloads.append(decoded)
    return payloads


def candidate_views(text: str) -> List[Tuple[str, str]]:
    """
    Return unique (view_name, view_text) pairs, cheapest first.

    The 'unaccented' view is the most processed one and must be matched with
    accent-stripped patterns (see Layer1Prefilter).
    """
    normalized = strip_invisible(text)
    collapsed = collapse_separators(normalized)
    slang = clean_text(normalized, expand_slang=True)
    unaccented = remove_vietnamese_accents(collapse_separators(slang))

    ordered = [("raw", text), ("normalized", normalized), ("collapsed", collapsed), ("slang", slang)]
    if any(c in _LEET_CHARS for c in normalized):
        # Accent-free like the "unaccented" view, so it is matched with the accent-stripped patterns.
        ordered.append(("leet", remove_vietnamese_accents(collapse_separators(decode_leetspeak(normalized)))))
    for payload in _decoded_payloads(normalized):
        ordered.append(("decoded", strip_invisible(payload)))
    ordered.append(("unaccented", unaccented))

    seen = set()
    views: List[Tuple[str, str]] = []
    for name, view in ordered:
        if name == "leet" and view == unaccented:
            continue  # decoding changed nothing that the unaccented view does not already cover
        if name in ACCENT_FREE_VIEWS or view not in seen:
            seen.add(view)
            views.append((name, view))
    return views
