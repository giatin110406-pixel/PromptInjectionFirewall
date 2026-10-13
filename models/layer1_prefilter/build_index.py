"""
Build the Layer 1 semantic index (replaces the old ChromaDB build).

Entries come from the TRAIN split only. Validation is used to pick thresholds and test is only
for the final report, so neither may leak into the index: an attack template that sits in the
index scores 1.0 against itself and would hide how the layer treats attacks it has never seen.

    attack  : data hand-written pattern list, bare attack messages, and every sentence that was
              inserted into a document or message as an attack (all surface variants)
    benign  : ordinary prompts and replies, harmless inserted notes, document sentences, and the
              "User intent" lines that open every document row

A text that appears with both labels is ambiguous and is dropped.

    python models/layer1_prefilter/build_index.py
    python models/layer1_prefilter/build_index.py --model intfloat/multilingual-e5-small --out models/layer1_prefilter/index_e5
"""
import argparse
import json
import os
import random
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from firewall.embedder import DEFAULT_MODEL, Embedder, SentenceTransformerEmbedder  # noqa: E402
from firewall.signature_index import ATTACK, BENIGN, SignatureIndex  # noqa: E402
from data.scripts.vietnamese_norm import remove_vietnamese_accents  # noqa: E402
from firewall.text_units import split_units  # noqa: E402

TRAIN_CSV = os.path.join(BASE_DIR, "data", "processed", "dataset_v2_train.csv")
PATTERNS = os.path.join(BASE_DIR, "models", "layer1_prefilter", "jailbreak_patterns.json")
DEFAULT_OUT = os.path.join(BASE_DIR, "models", "layer1_prefilter", "index")
SUPPORT_ACTIONS = os.path.join(BASE_DIR, "data", "seeds", "benign_support_actions.json")
MAX_ENTRY_CHARS = 300


def _short(text: Any) -> str:
    text = " ".join(str(text).split())
    return text if 4 <= len(text) <= MAX_ENTRY_CHARS else ""


def collect_entries(train: pd.DataFrame, patterns: List[str], doc_sentences: int = 600, seed: int = 0) -> List[Dict[str, Any]]:
    if "split" in train.columns and set(train["split"].unique()) - {"train"}:
        raise ValueError("the index must be built from the train split only (found other splits)")
    found: Dict[tuple, str] = {}

    def add(text: str, label: int, source: str) -> None:
        text = _short(text)
        if text:
            found.setdefault((text, label), source)

    for pattern in patterns:
        add(pattern, ATTACK, "patterns")

    attacks = train[train["label_binary"] == 1]
    # "hard_*" = chat-sized hard cases written for L1/L2 (data/scripts/hard_cases.py), both labels, train split only
    for row in attacks[attacks["variant"].isin(["pure_attack", "raw"]) | attacks["variant"].str.startswith("hard_")].itertuples():
        add(row.text, ATTACK, f"attack:{row.source}")
    for sentence in attacks[attacks["variant"].str.startswith("attack_insert")]["insert_text"].dropna().unique():
        add(sentence, ATTACK, "attack:inserted")

    safes = train[train["label_binary"] == 0]
    short = safes[(safes["variant"].isin(["clean", "raw"]) | safes["variant"].str.startswith("hard_")) & (safes["source"] != "doc_base")]
    for row in short.itertuples():
        add(row.text, BENIGN, f"benign:{row.source}")
    # The harmless notes inserted into benign_insert rows come from ONE bank shared by every split
    # (only attack templates are split by template). Indexing them would put the same sentence in the
    # index and in validation/test, so those texts would match themselves at similarity 1.0 and the
    # false positive rate would look better than it is. They are deliberately left out.

    if os.path.exists(SUPPORT_ACTIONS):
        with open(SUPPORT_ACTIONS, "r", encoding="utf-8") as handle:
            for group in json.load(handle)["groups"].values():
                for sentences in group.values():
                    for sentence in sentences:
                        add(sentence, BENIGN, "benign:support_actions")

    rng = random.Random(seed)
    docs = safes[(safes["variant"] == "clean") & (safes["source"] == "doc_base")]["text"].tolist()
    rng.shuffle(docs)
    sentences: List[str] = []
    for doc in docs:
        sentences.extend(split_units(doc))
        if len(sentences) >= doc_sentences * 4:
            break
    rng.shuffle(sentences)
    for sentence in sentences[:doc_sentences]:
        add(sentence, BENIGN, "benign:document")

    # Vietnamese typed without diacritics is common and the embedding model reads it poorly, so every
    # Vietnamese entry also gets an unaccented twin (same label).
    for (text, label), source in list(found.items()):
        plain = remove_vietnamese_accents(text)
        if plain != text:
            found.setdefault((plain, label), f"{source}+noaccent")

    conflicting = {text for (text, label) in found if (text, 1 - label) in found}
    return [{"text": text, "label": label, "source": source}
            for (text, label), source in found.items() if text not in conflicting]


def build(embedder: Embedder, out_dir: str = DEFAULT_OUT, train_csv: str = TRAIN_CSV,
          patterns_json: str = PATTERNS, doc_sentences: int = 600, seed: int = 0) -> SignatureIndex:
    train = pd.read_csv(train_csv)
    with open(patterns_json, "r", encoding="utf-8") as handle:
        patterns = json.load(handle)
    entries = collect_entries(train, patterns, doc_sentences, seed)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = ""
    index = SignatureIndex.build(entries, embedder, {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": commit or None,
        "train_csv": os.path.relpath(train_csv, BASE_DIR), "seed": seed, "doc_sentences": doc_sentences,
        "sources": dict(Counter(e["source"] for e in entries)),
    })
    index.save(out_dir)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--train", default=TRAIN_CSV)
    parser.add_argument("--patterns", default=PATTERNS)
    parser.add_argument("--doc-sentences", type=int, default=600)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    index = build(SentenceTransformerEmbedder(args.model), args.out, args.train, args.patterns, args.doc_sentences, args.seed)
    print(f"[INFO] {index.meta['n_entries']} entries ({index.meta['n_attack']} attack, {index.meta['n_benign']} benign), "
          f"model {index.meta['model']}, dim {index.meta['dim']} -> {args.out}")
    for source, count in sorted(index.meta["sources"].items()):
        print(f"       {source:28s} {count}")


if __name__ == "__main__":
    main()
