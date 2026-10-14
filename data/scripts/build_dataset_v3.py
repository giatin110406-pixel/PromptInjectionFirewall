"""
Build dataset v3: the same leakage controls as dataset v2, but the attack and safe SENTENCES come from public,
human-written data instead of sentences written by Claude.

What changes against v2 (docs/public_data_implementation_plan.md, plan B):
  dropped   Claude's attack and benign seed banks (7,520 + 910 + 194 template injections), chat_bank, and the BIPIA-GPT
            documents' inserted sentences. Nothing here reads data/seeds/.
  attacks   English: Tensor Trust (successful attacks, benchmark + raw dump) and InjecAgent attacker instructions.
            Vietnamese: kept from the AI-generated sets (tmdeptrai, llm_gen_vi, hard_cases); no public Vietnamese
            injection data exists, so these stay AI-generated and are flagged.
  safe      English: Dolly-15k instructions, responses and contexts. Vietnamese: XQuAD-vi questions and paragraphs, plus the
            AI-generated safe Vietnamese rows (so that style does not tell the label inside Vietnamese inserts).
  bases     Dolly contexts, XQuAD-vi paragraphs and a small slice of BIPIA-GPT documents (provenance unverified).

Same base text for both labels (clean / benign_insert / attack_insert x2), same insertion point, benign inserts
length-matched to the attack they are paired with, and every split decided per base text and per inserted sentence.
Held-out parts used later to measure the model are written to data/eval/public/holdout_*.csv:
  Tensor Trust attacks of the test split, InjecAgent cases whose attacker instruction is in the test group,
  Dolly and XQuAD-vi bases of the test split.

    python data/scripts/build_dataset_v3.py
Output: data/processed_public/dataset_v2_{train,validation,test}.csv (same file names, so train.py reads them with
--data-dir data/processed_public) and evaluation/results/dataset_v3_audit.json.
"""
import argparse
import bz2
import hashlib
import json
import os
import random
import re
import sys
from typing import Any, Dict, List

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts import build_dataset_v2 as v2  # noqa: E402
from data.scripts.build_dataset_v2 import (COLUMNS, SPLITS, _row, apply_transform, balance_labels, combine_chat,  # noqa: E402
                                           insert_sentence, load_doc_contexts, pick_length_matched, pick_transform,
                                           rng_for, split_of, validate_dataset)

RAW = os.path.join(BASE_DIR, "data", "raw", "public")
OUT_DIR = os.path.join(BASE_DIR, "data", "processed_public")
EVAL_DIR = os.path.join(BASE_DIR, "data", "eval", "public")
AUDIT = os.path.join(BASE_DIR, "evaluation", "results", "dataset_v3_audit.json")
V2_DIR = os.path.join(BASE_DIR, "data", "processed")
NEAR = 0.8
KEPT_AI_SOURCES = ("tmdeptrai", "llm_gen_vi", "hard_cases")   # Vietnamese-capable AI-generated rows kept as they are


def norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def short(key: str) -> str:
    """Collision-free id for a sentence (a prefix is not: many Tensor Trust attacks share their first words)."""
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def digest(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


# ----------------------------------------------------------------------------
# Public attack sentences
# ----------------------------------------------------------------------------
def tensor_trust_pool(seed: int) -> List[Dict[str, str]]:
    """Successful, unique, human-written attacks (raw dump v2) plus the two benchmarks, split by text.
    Near duplicates of a train text are removed from validation and test (people copy each other's attacks)."""
    texts: List[str] = []
    with bz2.open(os.path.join(RAW, "tensortrust", "raw_v2_attacks.jsonl.bz2"), "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            if str(r["output_is_access_granted"]).lower() != "true" or str(r["is_self_attack"]).lower() == "true":
                continue
            attack, code = str(r["attacker_input"] or ""), str(r["access_code"] or "")
            if attack and not (code and code.lower() in attack.lower()):
                texts.append(attack.strip())
    for fname in ("hijacking.jsonl", "extraction.jsonl"):
        texts += [json.loads(l)["attack"].strip() for l in open(os.path.join(RAW, "tensortrust", fname), encoding="utf-8")]
    unique: Dict[str, str] = {}
    for t in texts:
        if len(t) >= 20 and len(t) <= 3000:
            unique.setdefault(norm_key(t), t)
    items = [{"text": t, "key": k, "split": split_of("tt:" + k, seed)} for k, t in unique.items()]

    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    matrix = vec.fit_transform([i["text"][:600] for i in items])
    train_idx = [n for n, i in enumerate(items) if i["split"] == "train"]
    train_matrix = matrix[train_idx]
    removed = 0
    keep = []
    for n, item in enumerate(items):
        if item["split"] != "train":
            best = (matrix[n] @ train_matrix.T).max()
            if best >= NEAR:
                removed += 1
                continue
        keep.append(item)
    print(f"[INFO] tensor trust: {len(items)} unique, {removed} validation/test near-duplicates of train removed")
    return keep


def injecagent_pool(seed: int) -> List[Dict[str, str]]:
    """The 62 attacker instructions; split by instruction (35% test, 15% validation, 50% train)."""
    texts = []
    for fname in ("attacker_cases_dh.jsonl", "attacker_cases_ds.jsonl"):
        for line in open(os.path.join(RAW, "injecagent", fname), encoding="utf-8"):
            if line.strip():
                texts.append(json.loads(line)["Attacker Instruction"].strip())
    texts = sorted(set(texts), key=lambda t: digest("ia", seed, t))
    n_test, n_val = round(len(texts) * 0.35), round(len(texts) * 0.15)
    out = []
    for pos, t in enumerate(texts):
        out.append({"text": t, "key": norm_key(t), "split": "test" if pos < n_test else "validation" if pos < n_test + n_val else "train"})
    return out


# ----------------------------------------------------------------------------
# Public safe text
# ----------------------------------------------------------------------------
def dolly_records(seed: int) -> pd.DataFrame:
    rows = [json.loads(l) for l in open(os.path.join(RAW, "dolly", "databricks-dolly-15k.jsonl"), encoding="utf-8")]
    frame = pd.DataFrame(rows)
    frame["rid"] = [f"dolly:{i}" for i in range(len(frame))]
    frame["split"] = [split_of(r, seed) for r in frame["rid"]]
    return frame


def xquad_records(seed: int) -> pd.DataFrame:
    frame = pd.read_parquet(os.path.join(RAW, "xquad_vi", "validation.parquet"))
    frame["cid"] = [hashlib.sha1(c.encode("utf-8")).hexdigest()[:12] for c in frame["context"]]
    frame["split"] = [split_of("xq:" + c, seed) for c in frame["cid"]]
    return frame


def kept_ai_rows() -> pd.DataFrame:
    """Rows of dataset v2 that are kept: the AI-generated Vietnamese-capable sources, without the Claude template injections."""
    frames = [pd.read_csv(os.path.join(V2_DIR, f"dataset_v2_{s}.csv"), keep_default_na=False) for s in SPLITS]
    d = pd.concat(frames, ignore_index=True)
    keep = d["source"].isin(KEPT_AI_SOURCES) & d["synthetic_kind"].isin(["llm_generated", "hard_case", "base_text"])
    d = d[keep].copy()
    d["variant"] = "raw"                  # no longer part of a clean / insert pair
    d["template_id"] = ""
    d["insert_text"] = ""
    return d.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Rows
# ----------------------------------------------------------------------------
def render_doc(intent: str, context: str, sentence: str, where: float) -> str:
    ctx = context if sentence is None else insert_sentence(context, sentence, where)
    return f"User intent: {intent}\nExternal context:\n{ctx}"


class Pools:
    def __init__(self, seed: int, tt, ia, dolly, xq, ai):
        self.seed = seed
        self.attack: Dict[tuple, List[Dict]] = {}
        for item in tt:
            self.attack.setdefault((item["split"], "en", "tt"), []).append(dict(item, attack_type="tensortrust"))
        for item in ia:
            self.attack.setdefault((item["split"], "en", "ia"), []).append(dict(item, attack_type="injecagent"))
        for r in ai[(ai["label_binary"] == 1) & (ai["lang"] == "vi") & (ai["text"].str.len() <= 500)].itertuples():
            self.attack.setdefault((r.split, "vi", "ai"), []).append(
                {"text": r.text, "key": norm_key(r.text), "split": r.split, "attack_type": "ai_vi"})
        self.safe: Dict[tuple, List[str]] = {}
        for split, g in dolly.groupby("split"):
            pool = list(g["instruction"]) + list(g["response"])
            self.safe[(split, "en")] = [t.strip() for t in pool if 15 <= len(t.strip()) <= 3000]
        for split, g in xq.groupby("split"):
            pool = list(g["question"].unique())
            self.safe[(split, "vi")] = pool
        for r in ai[(ai["label_binary"] == 0) & (ai["lang"] == "vi") & (ai["text"].str.len() <= 500)].itertuples():
            self.safe.setdefault((r.split, "vi"), []).append(r.text.strip())

    def attack_sentence(self, rng, split: str, lang: str, used: set):
        if lang == "en":
            ia = self.attack.get((split, "en", "ia"), [])
            tt = self.attack[(split, "en", "tt")]
            pool = ia if (ia and rng.random() < 0.10) else tt
        else:
            pool = self.attack[(split, "vi", "ai")]
        fresh = [p for p in pool if p["key"] not in used] or pool
        item = rng.choice(fresh)
        used.add(item["key"])
        return item


def build_doc_rows(bases: pd.DataFrame, pools: Pools, seed: int, tag: str, p_vi_en_doc: float = 0.25) -> List[Dict]:
    """bases: orig_id, intent, context, lang, split. Four rows per base: clean, benign insert, two attack inserts."""
    rows = []
    for b in bases.itertuples(index=False):
        rng = rng_for(seed, tag, b.orig_id)
        where = rng.random()
        p_vi = p_vi_en_doc if b.lang == "en" else 0.8
        rows.append(_row(render_doc(b.intent, b.context, None, where), 0, b.lang, tag, "safe", b.orig_id, "", "clean", b.split, "human_base"))
        used: set = set()
        first = None
        for index in (1, 2):
            lang = "vi" if rng.random() < p_vi else "en"
            item = pools.attack_sentence(rng, b.split, lang, used)
            transform = pick_transform(rng, lang)
            sentence = apply_transform(item["text"], transform)
            if first is None:
                first = (lang, transform, sentence)
            rows.append(_row(render_doc(b.intent, b.context, sentence, where), 1, v2._lang_of_pair(b.lang, lang), tag,
                             item["attack_type"], b.orig_id, "ins:" + short(item["key"]) + f":{transform}", f"attack_insert_{index}", b.split,
                             "public_attack" if item["attack_type"] != "ai_vi" else "ai_vi_attack", sentence))
        lang, transform, sentence = first
        note = apply_transform(pick_length_matched(rng, pools.safe[(b.split, lang)], len(sentence)), transform)
        rows.append(_row(render_doc(b.intent, b.context, note, where), 0, v2._lang_of_pair(b.lang, lang), tag, "safe", b.orig_id, "",
                         "benign_insert", b.split, "public_safe", note))
    return rows


def build_chat_rows(bases: pd.DataFrame, pools: Pools, seed: int, tag: str, p_vi_en: float = 0.25) -> List[Dict]:
    """bases: orig_id, text, lang, split."""
    rows = []
    for b in bases.itertuples(index=False):
        rng = rng_for(seed, tag, b.orig_id)
        where = rng.random()
        p_vi = p_vi_en if b.lang == "en" else 0.8
        rows.append(_row(b.text, 0, b.lang, tag, "safe", b.orig_id, "", "clean", b.split, "human_base"))
        used: set = set()
        first = None
        for index in (1, 2):
            lang = "vi" if rng.random() < p_vi else "en"
            item = pools.attack_sentence(rng, b.split, lang, used)
            transform = pick_transform(rng, lang)
            sentence = apply_transform(item["text"], transform)
            if first is None:
                first = (lang, transform, sentence)
            rows.append(_row(combine_chat(b.text, sentence, where), 1, v2._lang_of_pair(b.lang, lang), tag, item["attack_type"], b.orig_id,
                             "ins:" + short(item["key"]) + f":{transform}", f"attack_insert_{index}", b.split,
                             "public_attack" if item["attack_type"] != "ai_vi" else "ai_vi_attack", sentence))
        lang, transform, sentence = first
        note = apply_transform(pick_length_matched(rng, pools.safe[(b.split, lang)], len(sentence)), transform)
        rows.append(_row(combine_chat(b.text, note, where), 0, v2._lang_of_pair(b.lang, lang), tag, "safe", b.orig_id, "",
                         "benign_insert", b.split, "public_safe", note))
    return rows


def build_pure_attack_rows(tt: List[Dict], quota: Dict[str, int], seed: int) -> List[Dict]:
    rows = []
    for split, n in quota.items():
        pool = sorted((i for i in tt if i["split"] == split), key=lambda i: digest("pure", seed, i["key"]))[:n]
        for item in pool:
            rows.append(_row(item["text"], 1, "en", "tensortrust_pure", "tensortrust", "tt:" + short(item["key"]), "pure:" + short(item["key"]),
                             "pure_attack", split, "public_attack"))
    return rows


# ----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-dolly-docs", type=int, default=2000)
    parser.add_argument("--n-dolly-chat", type=int, default=2000)
    parser.add_argument("--n-bipia-docs", type=int, default=1000)
    parser.add_argument("--n-xquad-chat", type=int, default=900)
    parser.add_argument("--pure-train", type=int, default=1500)
    args = parser.parse_args()
    seed = args.seed

    tt, ia = tensor_trust_pool(seed), injecagent_pool(seed)
    dolly, xq, ai = dolly_records(seed), xquad_records(seed), kept_ai_rows()
    pools = Pools(seed, tt, ia, dolly, xq, ai)

    # ---- bases
    d_ctx = dolly[dolly["context"].str.len().between(300, 4000)].sample(frac=1, random_state=seed)
    d_ctx = d_ctx.head(args.n_dolly_docs)
    dolly_docs = pd.DataFrame({"orig_id": d_ctx["rid"] + ":doc", "intent": d_ctx["instruction"], "context": d_ctx["context"], "lang": "en", "split": d_ctx["split"]})
    d_chat = dolly[dolly["instruction"].str.len() >= 10].sample(frac=1, random_state=seed + 1).head(args.n_dolly_chat)
    texts = [i if (not c or len(c) > 1000) else f"{i}\n\n{c}" for i, c in zip(d_chat["instruction"], d_chat["context"])]
    dolly_chat = pd.DataFrame({"orig_id": d_chat["rid"] + ":chat", "text": texts, "lang": "en", "split": d_chat["split"]})
    x_ctx = xq.drop_duplicates("cid")
    q_per_ctx = xq.groupby("cid")["question"].first()
    xq_docs = pd.DataFrame({"orig_id": "xq:" + x_ctx["cid"] + ":doc", "intent": [q_per_ctx[c] for c in x_ctx["cid"]], "context": x_ctx["context"], "lang": "vi", "split": x_ctx["split"]})
    x_q = xq.drop_duplicates("question").sample(frac=1, random_state=seed).head(args.n_xquad_chat)
    xq_chat = pd.DataFrame({"orig_id": "xq:" + x_q["id"] + ":chat", "text": x_q["question"], "lang": "vi", "split": x_q["split"]})
    bipia = load_doc_contexts(v2.DEFAULT_BIPIA, args.n_bipia_docs, seed)
    bipia["lang"] = "en"
    bipia["split"] = [split_of(o, seed) for o in bipia["orig_id"]]

    rows: List[Dict] = []
    rows += build_doc_rows(dolly_docs, pools, seed, "dolly_doc")
    rows += build_doc_rows(xq_docs, pools, seed, "xquad_vi_doc")
    rows += build_doc_rows(bipia, pools, seed, "bipia_doc")
    rows += build_chat_rows(dolly_chat, pools, seed, "dolly_chat")
    rows += build_chat_rows(xq_chat, pools, seed, "xquad_vi_chat")
    rows += build_pure_attack_rows(tt, {"train": args.pure_train, "validation": args.pure_train // 8, "test": args.pure_train // 8}, seed)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    kept = ai.copy()
    kept["is_synthetic"] = True
    frame = pd.concat([frame, kept[COLUMNS]], ignore_index=True)
    frame, balance_report = balance_labels(frame, seed)
    problems = validate_dataset(frame)
    print("[INFO] validation problems:", problems or "none")
    os.makedirs(OUT_DIR, exist_ok=True)
    for split in SPLITS:
        frame[frame["split"] == split].to_csv(os.path.join(OUT_DIR, f"dataset_v2_{split}.csv"), index=False, encoding="utf-8")

    # ---- held-out evaluation parts (never trained on)
    os.makedirs(EVAL_DIR, exist_ok=True)

    def write_holdout(name: str, texts, label, lang, source, attack_type="safe", ids=None):
        df = pd.DataFrame({"text": list(texts), "label_binary": label, "lang": lang, "source": source, "attack_type": attack_type,
                           "orig_id": ids if ids is not None else [f"{source}:{i}" for i in range(len(texts))], "split": "holdout_test"})
        df.to_csv(os.path.join(EVAL_DIR, f"holdout_{name}.csv"), index=False, encoding="utf-8")
        return len(df)

    holdout = {}
    holdout["tt"] = write_holdout("tensortrust", [i["text"] for i in tt if i["split"] == "test"], 1, "en", "tensortrust_holdout", "tensortrust")
    t = dolly[dolly["split"] == "test"]
    holdout["dolly_instr"] = write_holdout("dolly_instr", t[t["instruction"].str.len() >= 10]["instruction"].drop_duplicates().sample(1000, random_state=seed), 0, "en", "dolly_holdout")
    holdout["dolly_doc"] = write_holdout("dolly_doc", t[t["context"].str.len() >= 300]["context"].drop_duplicates().sample(300, random_state=seed), 0, "en", "dolly_doc_holdout")
    xt = xq[xq["split"] == "test"]
    holdout["xquad_q"] = write_holdout("xquad_q", xt["question"].drop_duplicates(), 0, "vi", "xquad_vi_holdout")
    holdout["xquad_doc"] = write_holdout("xquad_doc", xt["context"].drop_duplicates(), 0, "vi", "xquad_vi_doc_holdout")
    test_instr = {i["text"] for i in ia if i["split"] == "test"}
    cases = [json.loads(l) for l in open(os.path.join(EVAL_DIR, "injecagent_cases.jsonl"), encoding="utf-8")]
    benign_templates = pd.read_csv(os.path.join(EVAL_DIR, "injecagent_resp_base.csv"), keep_default_na=False)
    benign_templates = benign_templates[benign_templates["label_binary"] == 0]["text"].tolist()
    for setting in ("base", "enhanced"):
        atk = [c["tool_response"] for c in cases if c["setting"] == setting and c["attacker_instruction"].strip() in test_instr]
        holdout[f"injecagent_{setting}"] = write_holdout(f"injecagent_{setting}", atk + benign_templates, [1] * len(atk) + [0] * len(benign_templates), "en",
                                                         f"injecagent_{setting}_holdout", ["injecagent"] * len(atk) + ["safe"] * len(benign_templates))

    audit = {"seed": seed, "problems": problems, "balance": balance_report, "holdout_rows": holdout,
             "rows_by_split_label": {s: {str(k): int(v) for k, v in frame[frame.split == s].label_binary.value_counts().items()} for s in SPLITS},
             "rows_by_source": {s: {k: int(v) for k, v in frame[frame.split == s].source.value_counts().items()} for s in SPLITS},
             "attack_origin_train": {k: int(v) for k, v in frame[(frame.split == "train") & (frame.label_binary == 1)].synthetic_kind.value_counts().items()},
             "attack_rows_by_type_train": {k: int(v) for k, v in frame[(frame.split == "train") & (frame.label_binary == 1)].attack_type.value_counts().items()},
             "lang_by_split": {s: {k: int(v) for k, v in frame[frame.split == s].lang.value_counts().items()} for s in SPLITS},
             "tt_pool": {s: sum(1 for i in tt if i["split"] == s) for s in SPLITS}, "injecagent_pool": {s: sum(1 for i in ia if i["split"] == s) for s in SPLITS},
             "dataset_sha256": hashlib.sha256("\n".join(sorted(frame["text"])).encode("utf-8")).hexdigest()}
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps({k: audit[k] for k in ("rows_by_split_label", "attack_origin_train", "attack_rows_by_type_train", "lang_by_split", "holdout_rows", "tt_pool", "injecagent_pool")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
