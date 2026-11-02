"""
Build dataset v3c: dataset v3b unchanged, plus the H5 handoff rows (data/raw/handoff/).

Why: v3b fixed false blocks on ordinary banking requests but lost recall (WP7 criteria not met),
and on the v4 flows Layer 2 still taints legitimate Vietnamese documents (7 of 8 false blocks).
H5 adds what v3b lacks, as matched safe/attack pairs:
  tool_json.jsonl   320 pairs, 16 families: tool responses (JSON) with a note field
  vi_cskh.jsonl     240 customer-service pairs (24 families) + 120 unaccented/teencode money pairs (12 families)

What changes against v3b:
  added    H5 rows, `text` only. Split by `family` (both rows of a pair, every value swap and
           position of a family stay in one split), 80/10/10 inside each group (tool/cskh/money),
           at least one validation and one test family per group.
  dropped  H5 pairs where either row is too close to an evaluation set (exact after normalising,
           or char 3-5 TF-IDF cosine >= --eval-threshold) or to a v3b row of another split.
  kept     every v3b row verbatim.

H5 is AI-generated (OpenAI Codex) and has no independent label review; `is_synthetic` is True
and `synthetic_kind` is "h5_codex" on every added row.

Output: data/processed_public_v3c/dataset_v2_{train,validation,test}.csv
Audit:  evaluation/results/dataset_v3c_audit.json

Usage:
    python data/scripts/build_dataset_v3c.py
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from typing import Dict, List

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.build_dataset_v2 import COLUMNS, SPLITS, validate_dataset  # noqa: E402
from data.scripts.build_dataset_v3 import norm_key  # noqa: E402

V3B_DIR = os.path.join(BASE_DIR, "data", "processed_public_v3b")
H5_DIR = os.path.join(BASE_DIR, "data", "raw", "handoff")
OUT_DIR = os.path.join(BASE_DIR, "data", "processed_public_v3c")
AUDIT = os.path.join(BASE_DIR, "evaluation", "results", "dataset_v3c_audit.json")
VI_CHARS = re.compile(r"[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]", re.I)


def group_of(family: str) -> str:
    return "tool" if family.startswith("tool_") else "money" if family.startswith("money_") else "cskh"


def family_splits(families: List[str], seed: int) -> Dict[str, str]:
    """80/10/10 by hash inside each group, at least one validation and one test family per group."""
    out: Dict[str, str] = {}
    for group in sorted({group_of(f) for f in families}):
        ranked = sorted({f for f in families if group_of(f) == group},
                        key=lambda f: hashlib.sha256(f"h5_family|{seed}|{f}".encode()).hexdigest())
        n_test = n_val = max(1, round(len(ranked) * 0.1))
        for i, f in enumerate(ranked):
            out[f] = "test" if i < n_test else "validation" if i < n_test + n_val else "train"
    return out


def load_h5() -> pd.DataFrame:
    rows = []
    for name in ("tool_json.jsonl", "vi_cskh.jsonl"):
        for line in open(os.path.join(H5_DIR, name), encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    return pd.DataFrame(rows)


def eval_texts() -> List[str]:
    """Every text an evaluation reads: public sets, transactions, vi_test, external test, v4 scenarios and flows."""
    texts: List[str] = []
    for path in glob.glob(os.path.join(BASE_DIR, "data", "eval", "public", "*.csv")) + [
            os.path.join(BASE_DIR, "data", "eval", "vi_test_v1.csv"),
            os.path.join(BASE_DIR, "data", "eval", "tmdeptrai_external_test.csv")]:
        texts += pd.read_csv(path)["text"].dropna().astype(str).tolist()
    for path in glob.glob(os.path.join(BASE_DIR, "data", "eval", "*.jsonl")) + \
            glob.glob(os.path.join(BASE_DIR, "data", "eval", "*", "*.jsonl")):
        for line in open(path, encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            for key in ("text", "content", "tool_response", "attacker_instruction"):
                if isinstance(rec.get(key), str):
                    texts.append(rec[key])
            texts += [m for m in rec.get("user_messages", []) if isinstance(m, str)]
    return [t for t in texts if t.strip()]


def nearest(queries: List[str], refs: List[str]):
    """Best char 3-5 TF-IDF cosine of each query against refs, and the index of that ref."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1).fit(queries + refs)
    sims = vec.transform(queries) @ vec.transform(refs).T
    best = sims.max(axis=1).toarray().ravel()
    arg = sims.argmax(axis=1).A.ravel()
    return best, arg


def to_rows(h5: pd.DataFrame, splits: Dict[str, str]) -> pd.DataFrame:
    def lang(text: str, family: str) -> str:
        return "vi" if group_of(family) != "tool" or VI_CHARS.search(text) else "en"

    return pd.DataFrame({
        "text": h5["text"],
        "label_binary": h5["label"].astype(int),
        "label": ["INJECTION" if l else "SAFE" for l in h5["label"]],
        "lang": [lang(t, f) for t, f in zip(h5["text"], h5["family"])],
        "source": ["h5_" + group_of(f) for f in h5["family"]],
        "attack_type": ["h5_" + group_of(f) if l else "safe" for f, l in zip(h5["family"], h5["label"])],
        "orig_id": [f"{p}:{l}" for p, l in zip(h5["pair_id"], h5["label"])],
        "template_id": h5["family"],
        "variant": ["h5_attack" if l else "h5_safe" for l in h5["label"]],
        "split": [splits[f] for f in h5["family"]],
        "is_synthetic": True,
        "synthetic_kind": "h5_codex",
        "insert_text": "",          # short texts: one window each, the whole text carries the label
    })[COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--eval-threshold", type=float, default=0.8)
    args = parser.parse_args()

    v3b = pd.concat([pd.read_csv(os.path.join(V3B_DIR, f"dataset_v2_{s}.csv")) for s in SPLITS], ignore_index=True)
    h5 = load_h5()
    splits = family_splits(h5["family"].tolist(), args.seed)
    added = to_rows(h5, splits)

    # leakage: against evaluation sets (any split) and against v3b rows of a different split
    ev = eval_texts()
    ev_keys = {norm_key(t) for t in ev}
    exact_eval = added["text"].map(norm_key).isin(ev_keys)
    best_eval, _ = nearest(added["text"].tolist(), ev)
    best_v3b, arg_v3b = nearest(added["text"].tolist(), v3b["text"].astype(str).tolist())
    cross_split = (best_v3b >= args.eval_threshold) & (v3b["split"].to_numpy()[arg_v3b] != added["split"].to_numpy())
    bad = exact_eval.to_numpy() | (best_eval >= args.eval_threshold) | cross_split
    bad_pairs = set(h5.loc[bad, "pair_id"])
    keep = ~h5["pair_id"].isin(bad_pairs)
    added = added[keep.to_numpy()].reset_index(drop=True)

    frame = pd.concat([v3b[COLUMNS], added], ignore_index=True)
    problems = validate_dataset(frame)
    print("[INFO] validation problems:", problems or "none")
    os.makedirs(OUT_DIR, exist_ok=True)
    for split in SPLITS:
        path = os.path.join(OUT_DIR, f"dataset_v2_{split}.csv")
        frame[frame["split"] == split].to_csv(path, index=False, encoding="utf-8")
        print(f"[INFO] wrote {path} ({(frame['split'] == split).sum()} rows)")

    fam = pd.Series(splits)
    audit = {
        "seed": args.seed,
        "problems": problems,
        "base": "data/processed_public_v3b (unchanged)",
        "h5_rows_in": int(len(h5)),
        "h5_rows_added": int(len(added)),
        "h5_pairs_dropped_for_leakage": sorted(bad_pairs),
        "leakage_threshold": args.eval_threshold,
        "h5_max_similarity_to_eval": round(float(best_eval.max()), 4),
        "h5_max_similarity_to_v3b": round(float(best_v3b.max()), 4),
        "h5_families_by_split": {s: sorted(fam[fam == s].index) for s in SPLITS},
        "h5_rows_by_split_label": {s: {str(k): int(v) for k, v in added[added.split == s].label_binary.value_counts().items()} for s in SPLITS},
        "h5_rows_by_split_source": {s: {k: int(v) for k, v in added[added.split == s].source.value_counts().items()} for s in SPLITS},
        "rows_by_split_label": {s: {str(k): int(v) for k, v in frame[frame.split == s].label_binary.value_counts().items()} for s in SPLITS},
        "lang_by_split": {s: {k: int(v) for k, v in frame[frame.split == s].lang.value_counts().items()} for s in SPLITS},
        "data_authors": {"h5": "OpenAI Codex (AI-generated synthetic data; not human-authored; no independent label review)"},
    }
    audit["dataset_sha256"] = hashlib.sha256("\n".join(sorted(frame["text"].astype(str))).encode("utf-8")).hexdigest()
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps({k: audit[k] for k in ("h5_rows_added", "h5_pairs_dropped_for_leakage", "h5_max_similarity_to_eval",
                                            "h5_max_similarity_to_v3b", "h5_rows_by_split_source", "rows_by_split_label")},
                     indent=1, ensure_ascii=False))
    print(f"[INFO] audit wrote {AUDIT}")


if __name__ == "__main__":
    main()
