"""
Turn the public datasets downloaded into data/raw/public/ into evaluation CSVs (steps 2 and 3 of
docs/public_data_implementation_plan.md).

    python data/scripts/prepare_public_eval.py

Output, one file per set in data/eval/public/ with the columns of the other evaluation sets
(text, label_binary, lang, source, attack_type, orig_id, split = public_eval), plus
data/eval/public/injecagent_cases.jsonl (tool-call cases for the Layer 4 test) and
evaluation/results/public_prepare.json (counts, removed rows, overlap with project data, length per set).

Step 3 (overlap): a row is removed when its normalised text equals, or its character n-gram TF-IDF cosine
reaches NEAR with, any text the firewall was trained or tuned on: dataset_v2 (train, validation, test), the Layer 1
index, tmdeptrai external and vi_test_v1. Removed counts are reported per set.

Nothing here calls a model or a network. Sampling uses seed 0.
"""
import hashlib
import json
import os
import re
import sys
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.audit_leakage import _GERMAN  # noqa: E402
from data.scripts.vietnamese_norm import detect_language  # noqa: E402

RAW = os.path.join(BASE_DIR, "data", "raw", "public")
OUT = os.path.join(BASE_DIR, "data", "eval", "public")
REPORT = os.path.join(BASE_DIR, "evaluation", "results", "public_prepare.json")
NEAR = 0.8
MIN_CHARS = 20          # attack-only sets: shorter strings are not usable as a prompt
COLUMNS = ["text", "label_binary", "lang", "source", "attack_type", "orig_id", "split"]
SEED = 0


def norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def lang_of(text: str, forced: str = "") -> str:
    if forced:
        return forced
    if len(_GERMAN.findall(text)) >= 2:
        return "de"
    return detect_language(text)


def frame_from(texts, label, source, attack_type, lang="", orig_ids=None) -> pd.DataFrame:
    texts = [str(t) for t in texts]
    ids = orig_ids if orig_ids is not None else [f"{source}:{i}" for i in range(len(texts))]
    return pd.DataFrame({
        "text": texts,
        "label_binary": label if isinstance(label, list) else [label] * len(texts),
        "lang": [lang_of(t, lang) for t in texts],
        "source": source,
        "attack_type": attack_type if isinstance(attack_type, list) else [attack_type] * len(texts),
        "orig_id": ids,
        "split": "public_eval",
    })


# ----------------------------------------------------------------------------
# Loaders. Each returns a dict name -> DataFrame.
# ----------------------------------------------------------------------------
def load_deepset() -> Dict[str, pd.DataFrame]:
    parts = [pd.read_parquet(os.path.join(RAW, "deepset", f)) for f in sorted(os.listdir(os.path.join(RAW, "deepset")))
             if f.endswith(".parquet")]
    data = pd.concat(parts, ignore_index=True)
    label = data["label"].astype(int).tolist()
    return {"deepset": frame_from(data["text"], label, "deepset", ["injection" if v else "safe" for v in label])}


def load_tensortrust() -> Dict[str, pd.DataFrame]:
    out = {}
    for name, fname, kind in (("tensortrust_hijack", "hijacking.jsonl", "hijacking"),
                              ("tensortrust_extract", "extraction.jsonl", "extraction")):
        rows = [json.loads(line) for line in open(os.path.join(RAW, "tensortrust", fname), encoding="utf-8")]
        out[name] = frame_from([r["attack"] for r in rows], 1, name, kind, lang="en",
                               orig_ids=[f"tt:{r['sample_id']}" for r in rows])
    return out


def load_injecagent() -> Dict[str, pd.DataFrame]:
    base = os.path.join(RAW, "injecagent")
    out, cases = {}, []
    for setting in ("base", "enhanced"):
        attacks, benign = [], {}
        for kind in ("dh", "ds"):
            for i, case in enumerate(json.load(open(os.path.join(base, f"test_cases_{kind}_{setting}.json"), encoding="utf-8"))):
                cid = f"ia:{kind}:{setting}:{i}"
                attacks.append((cid, str(case["Tool Response"]), f"{kind}:{case['Attack Type']}"))
                template = str(case["Tool Response Template"]).replace("<Attacker Instruction>", "")
                benign[template] = f"ia:benign:{kind}:{i}"
                cases.append({"id": cid, "setting": setting, "kind": kind, "attack_type": case["Attack Type"],
                              "attacker_tools": case["Attacker Tools"], "attacker_instruction": case["Attacker Instruction"],
                              "user_tool": case["User Tool"], "tool_response": str(case["Tool Response"])})
        texts = [a[1] for a in attacks] + list(benign)
        labels = [1] * len(attacks) + [0] * len(benign)
        types = [a[2] for a in attacks] + ["safe"] * len(benign)
        ids = [a[0] for a in attacks] + list(benign.values())
        out[f"injecagent_resp_{setting}"] = frame_from(texts, labels, f"injecagent_{setting}", types, lang="en", orig_ids=ids)
    users = [json.loads(line) for line in open(os.path.join(base, "user_cases.jsonl"), encoding="utf-8")]
    out["injecagent_user"] = frame_from([u["User Instruction"] for u in users], 0, "injecagent_user", "safe", lang="en")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "injecagent_cases.jsonl"), "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    return out


def load_multijail() -> Dict[str, pd.DataFrame]:
    data = pd.read_csv(os.path.join(RAW, "multijail", "MultiJail.csv"), dtype=str, keep_default_na=False)
    return {"multijail_vi": frame_from(data["vi"], 1, "multijail_vi", "harmful_request", lang="vi", orig_ids=[f"mj:{i}" for i in data["id"]]),
            "multijail_en": frame_from(data["en"], 1, "multijail_en", "harmful_request", lang="en", orig_ids=[f"mj:{i}" for i in data["id"]])}


def load_grayswan() -> Dict[str, pd.DataFrame]:
    rows = [json.loads(line) for line in open(os.path.join(RAW, "grayswan", "ipi.jsonl"), encoding="utf-8")]
    return {"grayswan_ipi": frame_from([r["attack"] for r in rows], 1, "grayswan_ipi", [r["behavior_id"].strip() for r in rows], lang="en")}


def load_dolly() -> Dict[str, pd.DataFrame]:
    rows = [json.loads(line) for line in open(os.path.join(RAW, "dolly", "databricks-dolly-15k.jsonl"), encoding="utf-8")]
    data = pd.DataFrame(rows)
    data["i"] = range(len(data))
    instr = data[data["instruction"].str.len() >= 10].drop_duplicates("instruction").sample(2000, random_state=SEED)
    docs = data[data["context"].str.len() >= 300].drop_duplicates("context").sample(500, random_state=SEED)
    return {"dolly_instr": frame_from(instr["instruction"], 0, "dolly_instr", "safe", lang="en", orig_ids=[f"dolly:{i}" for i in instr["i"]]),
            "dolly_doc": frame_from(docs["context"], 0, "dolly_doc", "safe", lang="en", orig_ids=[f"dolly:{i}" for i in docs["i"]])}


def load_xquad() -> Dict[str, pd.DataFrame]:
    data = pd.read_parquet(os.path.join(RAW, "xquad_vi", "validation.parquet"))
    questions = data.drop_duplicates("question")
    contexts = data.drop_duplicates("context")
    return {"xquad_vi_q": frame_from(questions["question"], 0, "xquad_vi_q", "safe", lang="vi", orig_ids=list(questions["id"])),
            "xquad_vi_doc": frame_from(contexts["context"], 0, "xquad_vi_doc", "safe", lang="vi", orig_ids=list(contexts["id"]))}


LOADERS: List[Callable[[], Dict[str, pd.DataFrame]]] = [
    load_deepset, load_tensortrust, load_injecagent, load_multijail, load_grayswan, load_dolly, load_xquad]


# ----------------------------------------------------------------------------
# Step 3: overlap with everything the firewall saw
# ----------------------------------------------------------------------------
def project_texts() -> Dict[str, List[str]]:
    sets: Dict[str, List[str]] = {}
    for name in ("train", "validation", "test"):
        sets[f"dataset_v2_{name}"] = pd.read_csv(os.path.join(BASE_DIR, "data", "processed", f"dataset_v2_{name}.csv"),
                                                 keep_default_na=False)["text"].tolist()
    for name, path in (("tmdeptrai_external", "tmdeptrai_external_test.csv"), ("vi_test_v1", "vi_test_v1.csv")):
        sets[name] = pd.read_csv(os.path.join(BASE_DIR, "data", "eval", path), keep_default_na=False, encoding="utf-8-sig")["text"].tolist()
    entries = os.path.join(BASE_DIR, "models", "layer1_prefilter", "index", "entries.json")
    if os.path.exists(entries):
        raw = json.load(open(entries, encoding="utf-8"))
        sets["layer1_index"] = [str(e.get("text", e) if isinstance(e, dict) else e) for e in raw]
    return sets


def find_overlap(texts: List[str], ref: Dict[str, List[str]]) -> Dict[int, str]:
    """Row index -> name of the reference set it duplicates (exact first, then near)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    exact: Dict[str, str] = {}
    for name, items in ref.items():
        for t in items:
            exact.setdefault(norm_key(t), name)
    hits: Dict[int, str] = {}
    for i, t in enumerate(texts):
        if norm_key(t) in exact:
            hits[i] = f"exact:{exact[norm_key(t)]}"

    names, flat = [], []
    for name, items in ref.items():
        names += [name] * len(items)
        flat += [str(t)[:600] for t in items]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    ref_matrix = vectorizer.fit_transform(flat)
    todo = [i for i in range(len(texts)) if i not in hits]
    for start in range(0, len(todo), 500):
        batch = todo[start:start + 500]
        sims = vectorizer.transform([str(texts[i])[:600] for i in batch]) @ ref_matrix.T
        best = np.asarray(sims.max(axis=1).todense()).ravel()
        arg = np.asarray(sims.argmax(axis=1)).ravel()
        for k, i in enumerate(batch):
            if best[k] >= NEAR:
                hits[i] = f"near:{names[arg[k]]}"
    return hits


def length_auc(attack: pd.Series, safe: pd.Series) -> float:
    """P(attack longer than safe), ties half. Informational: shows how far length alone separates two sets."""
    a, s = np.sort(attack.str.len().to_numpy()), safe.str.len().to_numpy()
    left, right = np.searchsorted(a, s, side="left"), np.searchsorted(a, s, side="right")
    longer, tied = len(a) - right, right - left
    return float((longer + 0.5 * tied).sum() / (len(a) * len(s)))


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    ref = project_texts()
    print("[INFO] reference texts: " + ", ".join(f"{k}={len(v)}" for k, v in ref.items()))
    report: Dict[str, Dict] = {"reference_sizes": {k: len(v) for k, v in ref.items()}, "near_threshold": NEAR, "min_chars": MIN_CHARS, "sets": {}}
    frames: Dict[str, pd.DataFrame] = {}
    for loader in LOADERS:
        for name, frame in loader().items():
            raw_n = len(frame)
            frame = frame[frame["text"].str.strip() != ""]
            frame = frame.drop_duplicates("text")
            dedup_n = len(frame)
            if frame["label_binary"].nunique() == 1 and int(frame["label_binary"].iloc[0]) == 1:
                too_short = int((frame["text"].str.len() < MIN_CHARS).sum())
                frame = frame[frame["text"].str.len() >= MIN_CHARS]
            else:
                too_short = 0
            hits = find_overlap(frame["text"].tolist(), ref)
            kept = frame.reset_index(drop=True)
            overlap_rows = sorted(hits)
            examples = [{"text": kept["text"].iloc[i][:120], "match": hits[i]} for i in overlap_rows[:3]]
            kept = kept.drop(index=overlap_rows).reset_index(drop=True)
            kept[COLUMNS].to_csv(os.path.join(OUT, f"{name}.csv"), index=False, encoding="utf-8")
            frames[name] = kept
            report["sets"][name] = {
                "raw_rows": raw_n, "after_dedup": dedup_n, "removed_too_short": too_short,
                "removed_overlap_with_project": len(overlap_rows), "overlap_examples": examples, "final_rows": len(kept),
                "by_label": {str(k): int(v) for k, v in kept["label_binary"].value_counts().items()},
                "by_lang": {k: int(v) for k, v in kept["lang"].value_counts().items()},
                "chars_median": float(kept["text"].str.len().median()), "chars_p90": float(kept["text"].str.len().quantile(0.9)),
                "sha256": hashlib.sha256("\n".join(sorted(kept["text"])).encode("utf-8")).hexdigest(),
            }
            r = report["sets"][name]
            print(f"[{name}] raw={raw_n} dedup={dedup_n} short={too_short} overlap={len(overlap_rows)} final={len(kept)} "
                  f"labels={r['by_label']} median_chars={r['chars_median']:.0f}")

    # informational: how far length alone separates each attack set from each benign set
    attack_sets = [n for n, f in frames.items() if (f.label_binary == 1).all()]
    benign_sets = [n for n, f in frames.items() if (f.label_binary == 0).all()]
    report["length_auc_attack_vs_benign"] = {
        a: {b: round(length_auc(frames[a]["text"], frames[b]["text"]), 3) for b in benign_sets} for a in attack_sets}
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {REPORT}")


if __name__ == "__main__":
    main()
