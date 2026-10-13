"""
Layer 1: Signatures. Cheap checks that stop obvious attacks and let ordinary text through.

Two parts, in this order:

1. Regex signatures (English and Vietnamese). Matched against several normalized views of the
   text (firewall/normalize.py: invisible characters, look-alike letters, inserted separators,
   leetspeak, base64, no-diacritics). A hit is a BLOCK. Patterns follow the rules in
   firewall/baseline.py: bounded gaps, question-aware "soft" patterns.
2. Semantic index (firewall/signature_index.py). Each sentence is embedded with a multilingual
   model and compared with known attack and known benign sentences. It catches paraphrases that no
   regex lists. Thresholds come from calibration on the validation split.

Decisions: BLOCK (confident), ESCALATE (a weaker semantic signal, handed to Layer 2), PASS.

Failure behaviour (fail closed): if the semantic index or its embedding model cannot be loaded the
result carries `degraded=true`, and the orchestrator will not turn a degraded run into a final
ALLOW. Regex-only mode is available on purpose (`use_vector=False`) and is not "degraded".
"""
import functools
import re
from typing import Any, Dict, List, Optional, Tuple

from data.scripts.vietnamese_norm import remove_vietnamese_accents
from firewall.baseline import DEFAULT_BASELINE_PATTERNS, ESCALATE_HINT_PATTERNS, SOFT_BASELINE_PATTERNS
from firewall.embedder import DEFAULT_MODEL, Embedder, SentenceTransformerEmbedder
from firewall.normalize import ACCENT_FREE_VIEWS, candidate_views
from firewall.signature_index import IndexScore, SignatureIndex
from firewall.text_units import DEFAULT_MAX_UNITS

import os

DEFAULT_INDEX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "models", "layer1_prefilter", "index")

# Inputs larger than this are not scanned in full: a 1 MB blob is a resource attack or an
# attempt to bury an instruction, so it goes to Layer 2 instead of being waved through.
MAX_SCAN_CHARS = 200_000

# Extra English signatures on top of the shared baseline. Kept narrow on purpose:
# a bare "you are now" or "developer mode" also appears in ordinary support questions.
BLOCKED_REGEX_PATTERNS = DEFAULT_BASELINE_PATTERNS + [
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"disregard\s+(all\s+|prior\s+)?(prompts|rules)",
]

# A matching sentence that is a question is not an attack for SOFT patterns.
_QUESTION_MARKERS = re.compile(
    r"\?|\b(?:được|có)\s+không\b|\b(?:duoc|co)\s+khong\b"
    # asking what something IS is about the topic, not an attack
    r"|\b(?:là\s+gì|nghĩa\s+là|khái\s+niệm|định\s+nghĩa|la\s+gi|nghia\s+la|khai\s+niem|dinh\s+nghia)\b"
    r"|\b(?:what\s+is|what\s+does|meaning\s+of)\b",
    re.IGNORECASE,
)
# "Explain / translate / giải thích / dịch ..." only counts when it OPENS the sentence. Anywhere else
# it is just a word: "transfer the funds without verification, I will explain later" is an attack.
_EDUCATIONAL_OPENING = re.compile(
    r"^\W*(?:please\s+|hãy\s+|bạn\s+|vui\s+lòng\s+|nhờ\s+bạn\s+)?(?:explain|define|translate|giải\s+thích|dịch|giai\s+thich|dich)\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"[.?!\n]")


@functools.lru_cache(maxsize=2)
def shared_embedder(model_name: str = DEFAULT_MODEL) -> Embedder:
    """One loaded model per process: loading takes 10 to 35 seconds, and every Layer1Prefilter shares it."""
    return SentenceTransformerEmbedder(model_name)


class Layer1Prefilter:
    def __init__(
        self,
        index_dir: Optional[str] = None,
        embedder: Optional[Embedder] = None,
        use_vector: bool = True,
        max_units: int = DEFAULT_MAX_UNITS,
    ):
        """
        index_dir   directory written by models/layer1_prefilter/build_index.py (default: the shipped index)
        embedder    inject an embedder (tests use a small offline one); default loads the index's own model
        use_vector  False = regex only, on purpose (not reported as degraded)
        """
        self.use_vector = use_vector
        self.max_units = max_units
        self.index_dir = index_dir or DEFAULT_INDEX_DIR
        # (accented/ascii regex, accent-stripped twin, pattern text, is_soft)
        self.signatures = self._compile_signatures()
        self.regex_patterns = [sig[0] for sig in self.signatures]
        self.hints = [(re.compile(p, re.IGNORECASE), re.compile(remove_vietnamese_accents(p), re.IGNORECASE), p)
                      for p in ESCALATE_HINT_PATTERNS]
        self.index: Optional[SignatureIndex] = None
        self.embedder: Optional[Embedder] = embedder
        self.vector_error: Optional[str] = None
        if use_vector:
            self._init_vector_store()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _compile_signatures() -> List[Tuple["re.Pattern", "re.Pattern", str, bool]]:
        """Compile each pattern plus an accent-stripped twin for unaccented input."""
        entries = [(p, False) for p in dict.fromkeys(BLOCKED_REGEX_PATTERNS)]
        entries += [(p, True) for p in SOFT_BASELINE_PATTERNS if p not in BLOCKED_REGEX_PATTERNS]
        compiled = []
        for pattern, soft in entries:
            compiled.append((
                re.compile(pattern, re.IGNORECASE),
                re.compile(remove_vietnamese_accents(pattern), re.IGNORECASE),
                pattern,
                soft,
            ))
        return compiled

    def _init_vector_store(self) -> None:
        try:
            index = SignatureIndex.load(self.index_dir)
            embedder = self.embedder or shared_embedder(index.meta["model"])
            index.check_embedder(embedder)
            self.index, self.embedder = index, embedder
        except Exception as exc:  # missing index, missing model, wrong model, corrupted file
            self.index = None
            self.vector_error = f"{type(exc).__name__}: {exc}"

    @property
    def degraded(self) -> bool:
        """True when the semantic part was requested but is not available."""
        return self.use_vector and self.index is None

    # ------------------------------------------------------------------ regex part
    @staticmethod
    def _is_question_sentence(view: str, start: int, end: int) -> bool:
        left = max((m.end() for m in _SENTENCE_BREAK.finditer(view, 0, start)), default=0)
        right_match = _SENTENCE_BREAK.search(view, end)
        right = right_match.end() if right_match else len(view)
        sentence = view[left:right]
        return bool(_QUESTION_MARKERS.search(sentence) or _EDUCATIONAL_OPENING.match(sentence))

    def _match_signature(self, views: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
        """Return (pattern, view_name) for the first hard-signature hit, else None."""
        for view_name, view in views:
            accent_free = view_name in ACCENT_FREE_VIEWS
            for accented, stripped, pattern, soft in self.signatures:
                regex = stripped if accent_free else accented
                match = regex.search(view)
                if not match:
                    continue
                if soft and self._is_question_sentence(view, match.start(), match.end()):
                    continue
                return pattern, view_name
        return None

    def _match_hint(self, views: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
        """First ESCALATE-hint hit, as (pattern, view_name)."""
        for view_name, view in views:
            accent_free = view_name in ACCENT_FREE_VIEWS
            for accented, stripped, pattern in self.hints:
                if (stripped if accent_free else accented).search(view):
                    return pattern, view_name
        return None

    # ------------------------------------------------------------------ semantic part
    def semantic_text(self, views: List[Tuple[str, str]], text: str) -> str:
        """The view the embedder reads: NFKC + teencode expanded (the "slang" view), or the raw text."""
        return next((view for name, view in views if name == "slang"), text)

    def score_semantic(self, text: str) -> Optional[IndexScore]:
        """Semantic result for `text`, or None when the index is not available."""
        if self.index is None or self.embedder is None:
            return None
        return self.index.score_text(self.semantic_text(candidate_views(text), text), self.embedder, self.max_units)

    # ------------------------------------------------------------------ decision
    def check(self, text: str) -> Dict[str, Any]:
        """
        Execute Layer 1 checks.
        Returns:
            dict: {
                "layer": 1,
                "decision": "BLOCK" | "ESCALATE" | "PASS",
                "reason": str,
                "confidence": float,          # similarity to the closest known attack (1.0 for a regex hit)
                "matched_pattern": str | None,
                "matched_view": str | None,   # which normalized view matched (regex hits)
                "degraded": bool,
                ... semantic fields when the index ran
            }
        """
        base = {"layer": 1, "degraded": self.degraded}
        if not text or not isinstance(text, str):
            return {**base, "decision": "PASS", "reason": "empty_input", "confidence": 0.0, "matched_pattern": None}

        if len(text) > MAX_SCAN_CHARS:
            return {**base, "decision": "ESCALATE", "reason": f"oversized_input:{len(text)}_chars",
                    "confidence": 0.0, "matched_pattern": None}

        # 1. Regex signatures over normalized views (sub-millisecond)
        views = candidate_views(text)
        hit = self._match_signature(views)
        if hit:
            pattern, view_name = hit
            return {**base, "decision": "BLOCK", "reason": f"regex_match:{pattern}", "confidence": 1.0,
                    "matched_pattern": pattern, "matched_view": view_name}

        hint = self._match_hint(views)
        hint_result = None
        if hint:
            hint_result = {**base, "decision": "ESCALATE", "reason": f"regex_hint:{hint[0]}", "confidence": 0.5,
                           "matched_pattern": hint[0], "matched_view": hint[1]}

        # 2. Semantic index
        if not self.use_vector:
            return hint_result or {**base, "decision": "PASS", "reason": "regex_only_no_match", "confidence": 0.0, "matched_pattern": None}
        if self.index is None or self.embedder is None:
            return hint_result or {**base, "decision": "PASS", "reason": "semantic_index_unavailable", "confidence": 0.0,
                                   "matched_pattern": None, "vector_error": self.vector_error}

        score = self.index.score_text(self.semantic_text(views, text), self.embedder, self.max_units)
        detail = {
            "top_attack_similarity": round(score.attack_sim, 4), "top_benign_similarity": round(score.benign_sim, 4),
            "margin": round(score.margin, 4), "scored_unit": score.unit, "units_scored": score.n_units,
            "units_capped": score.capped,
        }
        if score.decision == "BLOCK":
            return {**base, "decision": "BLOCK", "reason": f"high_vector_similarity:{score.attack_sim:.3f}",
                    "confidence": round(score.attack_sim, 4), "matched_pattern": score.nearest_attack, **detail}
        if hint_result:  # the hint already escalates; keep it and attach the semantic detail
            return {**hint_result, **detail}
        if score.decision == "ESCALATE":
            return {**base, "decision": "ESCALATE", "reason": f"medium_vector_similarity:{score.attack_sim:.3f}",
                    "confidence": round(score.attack_sim, 4), "matched_pattern": score.nearest_attack, **detail}
        return {**base, "decision": "PASS", "reason": "low_similarity_no_match",
                "confidence": round(score.attack_sim, 4), "matched_pattern": None, **detail}
