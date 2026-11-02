"""
Argument provenance: where do the values in an action come from?

An agent that read an email and then asks to transfer money to account 0123456789 may be doing what the user asked,
or what the email asked. Layer 4 cannot tell from the wording, but it can tell from the VALUES: if the account number
appears in what the user typed (or in their saved recipients), the user chose it; if it appears only in the email,
the email chose it; if it appears nowhere, the agent made it up. Only the first case is cleared without a question.

This module:
  - extracts comparable values from text: account and phone numbers, emails, web hosts, order/ticket IDs;
  - parses Vietnamese amounts ("50tr", "2 tỷ 500 triệu", "1,5 triệu", "500k", "50.000.000đ") for the console;
  - keeps, per session, the values the user typed (trusted) and the values seen in untrusted content (with where);
  - reads the saved recipients of each user (trusted_book.yaml).

Matching is on whole values, never on substrings: "123456" is not trusted because the user typed "0123456789".
Short values (under 6 digits, or under 4 characters for IDs) are never trusted: they occur everywhere by chance.
State is in memory, like firewall/session.py, and expires after `ttl_seconds` without activity; with a StateStore
(FIREWALL_STATE_DB) it is written through to SQLite and reloaded per session, as in firewall/session.py.
"""
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

import yaml

from firewall.state_store import StateStore

DEFAULT_TTL_SECONDS = 30 * 60
DEFAULT_BOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trusted_book.yaml")
MIN_DIGITS = 6
MIN_ID_CHARS = 4
MAX_TOKENS_PER_SESSION = 5000      # a session pasting huge documents stops recording, it does not grow without end
MAX_REFS_PER_TOKEN = 5

TRUSTED, UNTRUSTED, UNKNOWN = "trusted", "untrusted", "unknown"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"(?<![\w+])\+?\d(?:[ .\-]?\d){5,18}(?![\w])")
_ALNUM_ID = re.compile(r"(?<![\w-])[A-Za-z]{1,10}[-_]?\d[A-Za-z0-9_-]*(?![\w-])")
_BARE_HOST = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
_SEPARATORS = re.compile(r"[\s.\-_]")


# ---------------------------------------------------------------- values
def _canon_digits(digits: str) -> str:
    """One spelling per number: separators gone, +84 / 84 phone prefixes written as 0."""
    digits = digits.lstrip("+")
    if len(digits) == 11 and digits.startswith("84"):
        digits = "0" + digits[2:]
    return digits


def _host(url: str) -> Optional[str]:
    if not re.match(r"https?://", url, re.IGNORECASE):
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host or None


def normalize_value(value: Any) -> Optional[str]:
    """The comparable form of one action argument, or None when it is empty."""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    if _EMAIL.fullmatch(text):
        return text.lower()
    if _URL.match(text):
        return _host(text)
    lowered = text.lower()
    if _BARE_HOST.fullmatch(lowered):                    # example-shop.vn written without http://
        return lowered[4:] if lowered.startswith("www.") else lowered
    compact = _SEPARATORS.sub("", lowered)
    if re.fullmatch(r"\+?\d+", compact):
        return _canon_digits(compact)
    return compact


def long_enough(key: Optional[str]) -> bool:
    if not key:
        return False
    if key.isdigit():
        return len(key) >= MIN_DIGITS
    if "@" in key or "." in key:                         # an email or a web host
        return True
    return len(key) >= MIN_ID_CHARS and any(ch.isdigit() for ch in key)


def extract_values(text: str) -> Set[str]:
    """Comparable values found in a text (account/phone numbers, emails, hosts, alphanumeric IDs)."""
    text = str(text or "")
    found: Set[str] = set()
    for match in _EMAIL.finditer(text):
        found.add(match.group(0).lower())
    for match in _URL.finditer(text):
        host = _host(match.group(0).rstrip(".,;:"))
        if host:
            found.add(host)
    for match in _DIGIT_RUN.finditer(text):
        run = match.group(0)
        found.add(_canon_digits(re.sub(r"[ .\-]", "", run)))
        # "0123 456 789, 50 triệu": also keep each long group on its own, in case two numbers were joined
        for group in re.split(r"\s+", run):
            plain = re.sub(r"[.\-]", "", group)
            if len(plain.lstrip("+")) >= MIN_DIGITS:
                found.add(_canon_digits(plain))
    for match in _ALNUM_ID.finditer(text):
        key = re.sub(r"[-_]", "", match.group(0)).lower()
        if len(key) >= MIN_ID_CHARS:
            found.add(key)
    return {v for v in found if long_enough(v)}


# ---------------------------------------------------------------- Vietnamese amounts
_UNIT_VALUES = {
    "tỷ": 10 ** 9, "tỉ": 10 ** 9, "ty": 10 ** 9, "tỏi": 10 ** 9,
    "triệu": 10 ** 6, "trieu": 10 ** 6, "tr": 10 ** 6, "củ": 10 ** 6,
    "nghìn": 10 ** 3, "nghin": 10 ** 3, "ngàn": 10 ** 3, "ngan": 10 ** 3, "k": 10 ** 3,
}
_NUMBER = r"\d+(?:[.,]\d+)*"
_UNIT_AMOUNT = re.compile(
    rf"(?<![\w.,])({_NUMBER})\s*(trăm\s*|tram\s*)?("
    + "|".join(sorted(map(re.escape, _UNIT_VALUES), key=len, reverse=True))
    + r")(?![^\W\d_])", re.IGNORECASE)
_CURRENCY_AMOUNT = re.compile(rf"(?<![\w.,])({_NUMBER})\s*(?:vnđ|vnd|đồng|dong|đ)(?![^\W\d_])", re.IGNORECASE)
_JOINER = re.compile(r"^\s*(?:lẻ|le|,)?\s*$", re.IGNORECASE)


def _number(text: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):        # 50.000.000 or 50,000,000: thousands separators
        return float(re.sub(r"[.,]", "", text))
    if re.fullmatch(r"\d+[.,]\d+", text):                    # 1,5 or 1.5: a decimal
        return float(text.replace(",", "."))
    return float(re.sub(r"[.,]", "", text))


def parse_amounts(text: str) -> List[int]:
    """Amounts in VND written the Vietnamese way. "2 tỷ 500 triệu" is one amount (2,500,000,000)."""
    text = str(text or "")
    amounts: List[int] = []
    group_total, group_unit, group_end = 0.0, None, None
    for match in _UNIT_AMOUNT.finditer(text):
        unit = _UNIT_VALUES[match.group(3).lower()]
        value = _number(match.group(1)) * (100 if match.group(2) else 1) * unit
        joined = group_unit is not None and unit < group_unit and _JOINER.match(text[group_end:match.start()])
        if joined:
            group_total += value
        else:
            if group_unit is not None:
                amounts.append(int(round(group_total)))
            group_total = value
        group_unit, group_end = unit, match.end()
    if group_unit is not None:
        amounts.append(int(round(group_total)))
    for match in _CURRENCY_AMOUNT.finditer(text):
        amounts.append(int(round(_number(match.group(1)))))
    return sorted(set(amounts))


def amount_key(value: Any) -> Optional[int]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(number)) if number > 0 else None


# ---------------------------------------------------------------- saved recipients
class TrustedBook:
    """Values a user has saved beforehand (a bank's beneficiary list, known billers). `everyone` applies to all users."""

    def __init__(self, users: Optional[Dict[str, Iterable[str]]] = None, everyone: Iterable[str] = ()):
        self._users = {str(u): {k for k in (normalize_value(v) for v in vals or ()) if k} for u, vals in (users or {}).items()}
        self._everyone = {k for k in (normalize_value(v) for v in everyone or ()) if k}

    def contains(self, user_id: Optional[str], key: str) -> bool:
        return key in self._everyone or (user_id is not None and key in self._users.get(str(user_id), set()))


def load_trusted_book(path: str = DEFAULT_BOOK) -> TrustedBook:
    """A missing file is an empty book: nothing is trusted beforehand (the safe side)."""
    if not os.path.exists(path):
        return TrustedBook()
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a valid trusted book")
    return TrustedBook(users=data.get("users") or {}, everyone=data.get("everyone") or ())


# ---------------------------------------------------------------- per-session ledger
NAMESPACE = "values"


class ValueLedger:
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS, clock=time.time, store: Optional[StateStore] = None):
        self.ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._store = store
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # ---- durable copy (no-ops without a StateStore); callers hold the lock
    def _sync(self, session_id: Optional[str]) -> None:
        if self._store is None or not session_id:
            return
        row = self._store.get(NAMESPACE, session_id)
        if row is None:
            self._sessions.pop(session_id, None)
            return
        self._sessions[session_id] = {
            "trusted": set(row["trusted"]), "untrusted": dict(row["untrusted"]),
            "trusted_amounts": set(row["trusted_amounts"]),
            "untrusted_amounts": {int(k): v for k, v in row["untrusted_amounts"].items()},
            "size": row["size"], "last_seen": row["last_seen"]}

    def _persist(self, session_id: str) -> None:
        if self._store is None:
            return
        state = self._sessions[session_id]
        self._store.put(NAMESPACE, session_id, {
            "trusted": sorted(state["trusted"]), "untrusted": state["untrusted"],
            "trusted_amounts": sorted(state["trusted_amounts"]),
            "untrusted_amounts": {str(k): v for k, v in state["untrusted_amounts"].items()},
            "size": state["size"], "last_seen": state["last_seen"]}, state["last_seen"])

    def _state(self, session_id: str) -> Dict[str, Any]:
        cutoff = self._clock() - self.ttl
        for key in [k for k, v in self._sessions.items() if v["last_seen"] < cutoff]:
            del self._sessions[key]
        if self._store is not None:
            self._store.delete_older(NAMESPACE, cutoff)
            self._sync(session_id)
        state = self._sessions.setdefault(session_id, {"trusted": set(), "untrusted": {}, "trusted_amounts": set(),
                                                       "untrusted_amounts": {}, "size": 0, "last_seen": 0.0})
        state["last_seen"] = self._clock()
        return state

    def _peek(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        state = self._sessions.get(session_id)
        if state is None or state["last_seen"] < self._clock() - self.ttl:
            return None
        return state

    def add_trusted(self, session_id: str, text: str) -> None:
        """Values the user typed in their own message."""
        with self._lock:
            state = self._state(session_id)
            for key in extract_values(text):
                if state["size"] < MAX_TOKENS_PER_SESSION and key not in state["trusted"]:
                    state["trusted"].add(key)
                    state["size"] += 1
            state["trusted_amounts"].update(parse_amounts(text))
            self._persist(session_id)

    def add_untrusted(self, session_id: str, text: str, source: str, chunk_id: Optional[str] = None) -> None:
        """Values seen in untrusted content, with where they were seen (for the reviewer)."""
        ref = {"source": source, "chunk_id": chunk_id}
        with self._lock:
            state = self._state(session_id)
            for store, keys in ((state["untrusted"], extract_values(text)), (state["untrusted_amounts"], parse_amounts(text))):
                for key in keys:
                    refs = store.get(key)
                    if refs is None:
                        if state["size"] >= MAX_TOKENS_PER_SESSION:
                            continue
                        refs = store[key] = []
                        state["size"] += 1
                    if ref not in refs and len(refs) < MAX_REFS_PER_TOKEN:
                        refs.append(ref)
            self._persist(session_id)

    def classify(self, session_id: Optional[str], value: Any, user_id: Optional[str] = None,
                 book: Optional[TrustedBook] = None) -> Dict[str, Any]:
        """{"origin": trusted | untrusted | unknown, "seen_in": [...]} for one action argument."""
        key = normalize_value(value)
        if not long_enough(key):
            return {"origin": UNKNOWN, "seen_in": [], "note": "too_short_to_trust"}
        with self._lock:
            self._sync(session_id)
            state = self._peek(session_id)
            if state is not None and key in state["trusted"]:
                return {"origin": TRUSTED, "seen_in": [{"source": "user"}]}
            if book is not None and book.contains(user_id, key):
                return {"origin": TRUSTED, "seen_in": [{"source": "trusted_book"}]}
            if state is not None and key in state["untrusted"]:
                return {"origin": UNTRUSTED, "seen_in": list(state["untrusted"][key])}
        return {"origin": UNKNOWN, "seen_in": []}

    def classify_amount(self, session_id: Optional[str], value: Any) -> Dict[str, Any]:
        """Where an amount was written. Informative only: small numbers occur everywhere, so they decide nothing."""
        key = amount_key(value)
        with self._lock:
            self._sync(session_id)
            state = self._peek(session_id)
            if key is None or state is None:
                return {"origin": UNKNOWN, "seen_in": []}
            if key in state["trusted_amounts"]:
                return {"origin": TRUSTED, "seen_in": [{"source": "user"}]}
            if key in state["untrusted_amounts"]:
                return {"origin": UNTRUSTED, "seen_in": list(state["untrusted_amounts"][key])}
        return {"origin": UNKNOWN, "seen_in": []}

    def summary(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            self._sync(session_id)
            state = self._peek(session_id)
            if state is None:
                return {"trusted": [], "untrusted": {}, "trusted_amounts": [], "untrusted_amounts": {}}
            return {"trusted": sorted(state["trusted"]), "untrusted": {k: list(v) for k, v in state["untrusted"].items()},
                    "trusted_amounts": sorted(state["trusted_amounts"]),
                    "untrusted_amounts": {str(k): list(v) for k, v in state["untrusted_amounts"].items()}}

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)
            if self._store is not None:
                self._store.delete(NAMESPACE, session_id)
