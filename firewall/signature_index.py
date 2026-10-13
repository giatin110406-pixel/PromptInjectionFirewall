"""
Vector index of known attack and known-benign sentences (Layer 1, semantic part).

How a text is judged:
  1. split it into sentences (firewall/text_units.py),
  2. embed every sentence,
  3. for each sentence take the closest known ATTACK (a) and the closest known BENIGN (b),
  4. a sentence is an attack signal only if it is close to an attack AND clearly closer to it
     than to anything benign: a >= threshold and a - b >= margin.

Comparing against benign exemplars is what keeps customer questions that merely mention
"password" or "OTP" from being blocked: they sit near benign anchors, not near attacks.

Everything is a numpy matrix in memory. A few thousand vectors need no database: a matrix
product over 1,000 x 384 floats takes well under a millisecond.

Files written by `save` (a directory):
    vectors.npy      float32, unit length, one row per entry
    entries.json     [{"text", "label", "source"}], same order as the rows
    meta.json        model name, dimension, build info, content hash
    thresholds.json  decision thresholds (written by calibration, read at load)
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from firewall.embedder import Embedder
from firewall.text_units import DEFAULT_MAX_UNITS, PREPARE_VERSION, prepare_unit, split_units, was_capped

ATTACK, BENIGN = 1, 0


@dataclass
class Thresholds:
    block_sim: float = 0.80          # unit is this close to a known attack ...
    block_margin: float = 0.05       # ... and at least this much closer to it than to anything benign
    escalate_sim: float = 0.65       # weaker signal: hand over to Layer 2
    escalate_margin: float = 0.0
    calibrated_on: str = "defaults (not calibrated)"
    notes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UnitScore:
    unit: str
    attack_sim: float
    benign_sim: float
    nearest_attack: str

    @property
    def margin(self) -> float:
        return self.attack_sim - self.benign_sim


@dataclass
class IndexScore:
    decision: str                      # "BLOCK" | "ESCALATE" | "PASS"
    attack_sim: float                  # of the representative unit
    benign_sim: float
    margin: float
    unit: str                          # the sentence that decided
    nearest_attack: str
    n_units: int
    capped: bool                       # True when sentences were skipped because of the unit cap


def _content_hash(texts: Sequence[str], labels: Sequence[int]) -> str:
    digest = hashlib.sha256()
    for text, label in zip(texts, labels):
        digest.update(f"{label}\t{text}\n".encode("utf-8"))
    return digest.hexdigest()


class SignatureIndex:
    def __init__(self, vectors: np.ndarray, entries: List[Dict[str, Any]], meta: Dict[str, Any],
                 thresholds: Optional[Thresholds] = None):
        if len(vectors) != len(entries):
            raise ValueError(f"{len(vectors)} vectors but {len(entries)} entries")
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.entries = entries
        self.meta = meta
        self.thresholds = thresholds or Thresholds()
        self.labels = np.array([int(e["label"]) for e in entries], dtype=np.int8)
        self._attack_cols = np.flatnonzero(self.labels == ATTACK)
        self._benign_cols = np.flatnonzero(self.labels == BENIGN)

    # ------------------------------------------------------------------ build / persist
    @classmethod
    def build(cls, entries: List[Dict[str, Any]], embedder: Embedder,
              meta: Optional[Dict[str, Any]] = None) -> "SignatureIndex":
        texts = [e["text"] for e in entries]
        labels = [int(e["label"]) for e in entries]
        vectors = embedder.encode([prepare_unit(t) for t in texts])  # same preparation as at query time
        info = {"model": embedder.name, "dim": int(vectors.shape[1]), "n_entries": len(entries),
                "prepare_version": PREPARE_VERSION,
                "n_attack": int(sum(labels)), "n_benign": int(len(labels) - sum(labels)),
                "content_sha256": _content_hash(texts, labels), **(meta or {})}
        return cls(vectors, entries, info)

    def save(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        np.save(os.path.join(directory, "vectors.npy"), self.vectors)
        with open(os.path.join(directory, "entries.json"), "w", encoding="utf-8") as handle:
            json.dump(self.entries, handle, ensure_ascii=False)
        with open(os.path.join(directory, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump(self.meta, handle, ensure_ascii=False, indent=2)
        self.save_thresholds(directory)

    def save_thresholds(self, directory: str) -> None:
        with open(os.path.join(directory, "thresholds.json"), "w", encoding="utf-8") as handle:
            json.dump(asdict(self.thresholds), handle, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, directory: str) -> "SignatureIndex":
        vectors = np.load(os.path.join(directory, "vectors.npy"))
        with open(os.path.join(directory, "entries.json"), "r", encoding="utf-8") as handle:
            entries = json.load(handle)
        with open(os.path.join(directory, "meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        thresholds = Thresholds()
        path = os.path.join(directory, "thresholds.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                thresholds = Thresholds(**json.load(handle))
        index = cls(vectors, entries, meta, thresholds)
        if meta.get("prepare_version") != PREPARE_VERSION:
            raise ValueError(f"index was built with text preparation v{meta.get('prepare_version')}, "
                             f"code is v{PREPARE_VERSION}: rebuild it with models/layer1_prefilter/build_index.py")
        stored = meta.get("content_sha256")
        actual = _content_hash([e["text"] for e in entries], [int(e["label"]) for e in entries])
        if stored and stored != actual:
            raise ValueError("index entries do not match their recorded hash: the index is corrupted or was edited by hand")
        return index

    # ------------------------------------------------------------------ scoring
    def score_vectors(self, units: List[str], unit_vectors: np.ndarray) -> List[UnitScore]:
        """Closest attack and closest benign entry for every unit."""
        if len(units) == 0:
            return []
        if self.vectors.shape[1] != unit_vectors.shape[1]:
            raise ValueError(f"embedding size {unit_vectors.shape[1]} does not match the index ({self.vectors.shape[1]})")
        sims = unit_vectors @ self.vectors.T
        scores: List[UnitScore] = []
        for row, unit in zip(sims, units):
            a_idx = self._attack_cols[int(np.argmax(row[self._attack_cols]))] if len(self._attack_cols) else None
            a = float(row[a_idx]) if a_idx is not None else 0.0
            b = float(row[self._benign_cols].max()) if len(self._benign_cols) else 0.0
            nearest = self.entries[a_idx]["text"] if a_idx is not None else ""
            scores.append(UnitScore(unit, a, b, nearest))
        return scores

    def decide_unit(self, score: UnitScore) -> str:
        t = self.thresholds
        if score.attack_sim >= t.block_sim and score.margin >= t.block_margin:
            return "BLOCK"
        if score.attack_sim >= t.escalate_sim and score.margin >= t.escalate_margin:
            return "ESCALATE"
        return "PASS"

    def judge(self, unit_scores: List[UnitScore], capped: bool = False) -> IndexScore:
        """Text-level result: the most severe unit decides, ties go to the closest attack."""
        if not unit_scores:
            return IndexScore("PASS", 0.0, 0.0, 0.0, "", "", 0, capped)
        order = {"BLOCK": 2, "ESCALATE": 1, "PASS": 0}
        decided = [(order[self.decide_unit(s)], s.attack_sim, s) for s in unit_scores]
        severity, _, best = max(decided, key=lambda item: (item[0], item[1]))
        decision = {2: "BLOCK", 1: "ESCALATE", 0: "PASS"}[severity]
        return IndexScore(decision, best.attack_sim, best.benign_sim, best.margin, best.unit,
                          best.nearest_attack, len(unit_scores), capped)

    def score_text(self, text: str, embedder: Embedder, max_units: int = DEFAULT_MAX_UNITS) -> IndexScore:
        units = split_units(text, max_units=max_units)
        vectors = embedder.encode([prepare_unit(u) for u in units]) if units else np.zeros((0, self.vectors.shape[1]), dtype=np.float32)
        return self.judge(self.score_vectors(units, vectors), capped=was_capped(text, max_units))

    def check_embedder(self, embedder: Embedder) -> None:
        """Refuse to compare vectors made by a different model: the numbers would be meaningless."""
        if self.meta.get("model") != embedder.name or self.meta.get("dim") != embedder.dim:
            raise ValueError(f"index was built with {self.meta.get('model')} ({self.meta.get('dim')}d) "
                             f"but the embedder is {embedder.name} ({embedder.dim}d)")
