"""
Chunk-level examples for training the Layer 2 classifier (P3-T2).

Why: a document is cut to the model's window. With max_len 256, 18% of the attack documents
in dataset v2 lost the inserted attack sentence yet kept the label "attack": the model was
asked to find something that was not in its input. Production avoids this by scanning every
chunk of an untrusted document, so training must do the same:

  - cut each text into overlapping windows of at most `max_tokens`,
  - a window is an ATTACK only if it contains (most of) the inserted attack sentence,
  - every other window of an attack document is SAFE: it is ordinary document text,
  - a window that holds only a fragment of the sentence is dropped (ambiguous).

Pure Python and tokenizer-agnostic: pass any function that returns the (start, end) character
offset of every token. Nothing here imports torch or transformers, so it is unit-tested without
a model.
"""
import hashlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

Offsets = Sequence[Tuple[int, int]]

MIN_ATTACK_OVERLAP = 0.6   # share of the inserted sentence a window must contain to be an attack
MAX_ATTACK_OVERLAP_DROP = 0.0  # overlap in (0, MIN_ATTACK_OVERLAP) is dropped as ambiguous


@dataclass
class Chunk:
    text: str
    label: int
    start: int          # character span inside the source text
    end: int
    overlap: float      # share of the inserted sentence inside this window (0 when none)


def token_windows(n_tokens: int, max_tokens: int, stride: int) -> List[Tuple[int, int]]:
    """Token index windows [a, b) of at most max_tokens, moving by `stride`; the last window reaches the end."""
    if n_tokens <= 0:
        return []
    if max_tokens <= 0 or stride <= 0:
        raise ValueError("max_tokens and stride must be positive")
    if n_tokens <= max_tokens:
        return [(0, n_tokens)]
    windows, start = [], 0
    while True:
        end = min(start + max_tokens, n_tokens)
        windows.append((start, end))
        if end == n_tokens:
            return windows
        start += stride


def find_insert_span(text: str, insert_text: Optional[str]) -> Optional[Tuple[int, int]]:
    """Character span of the inserted sentence, or None when nothing was inserted or it is not found."""
    if not insert_text:
        return None
    index = text.find(insert_text)
    return (index, index + len(insert_text)) if index >= 0 else None


def overlap_share(window: Tuple[int, int], span: Tuple[int, int]) -> float:
    """Fraction of `span` that lies inside `window` (both are character ranges)."""
    inside = max(0, min(window[1], span[1]) - max(window[0], span[0]))
    return inside / max(span[1] - span[0], 1)


def make_chunks(
    text: str,
    label: int,
    offsets: Offsets,
    insert_text: Optional[str] = None,
    max_tokens: int = 200,
    stride: int = 128,
) -> List[Chunk]:
    """
    Cut `text` into labelled windows.

    `offsets` are the character spans of the text's tokens in order (special tokens excluded).
    A text with label 0 yields only safe windows. A text with label 1 and a recorded
    `insert_text` yields attack windows where the sentence is, and safe windows elsewhere. A text
    with label 1 and no recorded sentence (a bare attack message, a generated row) is not cut
    further when it fits one window; when it does not fit, every window keeps the document label
    only if no better information exists, so callers should avoid long unlabelled attack texts.
    """
    windows = token_windows(len(offsets), max_tokens, stride)
    if not windows:
        return []
    span = find_insert_span(text, insert_text) if label == 1 else None
    chunks: List[Chunk] = []
    for a, b in windows:
        start, end = offsets[a][0], offsets[b - 1][1]
        piece = text[start:end]
        if not piece.strip():
            continue
        if label == 0:
            chunks.append(Chunk(piece, 0, start, end, 0.0))
        elif span is None:
            chunks.append(Chunk(piece, 1, start, end, 1.0))
        else:
            share = overlap_share((start, end), span)
            if share >= MIN_ATTACK_OVERLAP:
                chunks.append(Chunk(piece, 1, start, end, share))
            elif share == MAX_ATTACK_OVERLAP_DROP:
                chunks.append(Chunk(piece, 0, start, end, 0.0))
            # else: a fragment of the sentence only. Ambiguous, so it is dropped.
    return chunks


def _digest(*parts: object) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def balance_chunks(examples: List[Dict], seed: int = 0, ratio: float = 1.0) -> List[Dict]:
    """
    Keep every attack chunk and as many safe chunks as `ratio` x attacks, chosen deterministically.
    Chunking multiplies safe windows (a long benign document gives several), so without this the
    classes would be badly skewed.
    """
    attacks = [e for e in examples if e["label"] == 1]
    safes = sorted((e for e in examples if e["label"] == 0), key=lambda e: _digest(seed, e["chunk_id"]))
    return attacks + safes[: int(len(attacks) * ratio)]


def build_examples(
    rows: List[Dict],
    offsets_fn: Callable[[str], Offsets],
    max_tokens: int = 200,
    stride: int = 128,
) -> List[Dict]:
    """
    rows: dicts with text, label_binary, insert_text, orig_id, lang, source, variant.
    Returns one example per window: text, label, and the provenance needed for per-language reports.
    """
    examples: List[Dict] = []
    for row in rows:
        text = str(row["text"])
        chunks = make_chunks(text, int(row["label_binary"]), offsets_fn(text),
                             str(row.get("insert_text") or ""), max_tokens, stride)
        for position, chunk in enumerate(chunks):
            examples.append({
                "text": chunk.text, "label": chunk.label, "orig_id": row["orig_id"],
                "lang": row.get("lang", ""), "source": row.get("source", ""), "variant": row.get("variant", ""),
                "attack_type": row.get("attack_type", ""), "chunk_id": f"{row['orig_id']}#{row.get('variant', '')}#{position}",
                "doc_label": int(row["label_binary"]),
            })
    return examples


def aggregate_document_scores(chunk_scores: List[Tuple[str, float]], threshold: float) -> Dict[str, int]:
    """Document-level decision, as in production: a document is an attack if ANY chunk crosses the threshold."""
    flagged: Dict[str, int] = {}
    for doc_id, score in chunk_scores:
        flagged[doc_id] = max(flagged.get(doc_id, 0), int(score >= threshold))
    return flagged
