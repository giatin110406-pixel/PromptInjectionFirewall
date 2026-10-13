"""
Build the leakage-controlled training dataset v2 (P2-T2).

Why this exists: the v1 Layer 3 data took attacks from one source (BIPIA) and safe rows
from another (GPT-4o-mini), so "which source" decided the label (see
docs/data_audit_report.md). Here both labels are built from the SAME base text. Only the
inserted sentence differs:

    clean            base text, nothing inserted                         label 0
    benign_insert    base text + a harmless note/addendum                label 0
    attack_insert x2 base text + an instruction aimed at the AI          label 1

Controls:
- Same base text, same insertion position and the same surface transform
  (no-accent / teencode) for both labels, so style cannot predict the label.
- Benign inserts are length-matched to the attack they are paired with.
- Splits are decided per base text (`orig_id`) and per attack template (`template_id`):
  a template used in test never appears in train, so a model cannot just memorise phrases.
- The result is audited with data/scripts/audit_leakage.py and written next to the data.

Bases: documents (BIPIA-GPT benign contexts, English), short chat prompts (hand-written
support questions + tmdeptrai3012 benign rows, Vietnamese/English), and the raw
tmdeptrai3012 TRAIN rows (LLM-generated, kept as-is). Its test.jsonl is held out as an
external test set (data/eval/tmdeptrai_external_test.csv) and is never trained on.

Everything here is synthetic. `is_synthetic` and `synthetic_kind` say how each row was made.
This script does not read or write the human-written Vietnamese test set.

Usage:
    python data/scripts/build_dataset_v2.py --n-docs 3000
    python data/scripts/build_dataset_v2.py --no-tmdeptrai --bipia-jsonl path.jsonl
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.vietnamese_norm import detect_language, remove_vietnamese_accents  # noqa: E402

SEED_DIR = os.path.join(BASE_DIR, "data", "seeds")
OUT_DIR = os.path.join(BASE_DIR, "data", "processed")
RESULTS_DIR = os.path.join(BASE_DIR, "evaluation", "results")
DEFAULT_BIPIA = os.path.join(BASE_DIR, "dataset_for_huggingface.jsonl")

SPLITS = ("train", "validation", "test")
SPLIT_RATIOS = (0.8, 0.1, 0.1)
COLUMNS = [
    "text", "label_binary", "label", "lang", "source", "attack_type", "orig_id",
    "template_id", "variant", "split", "is_synthetic", "synthetic_kind", "insert_text",
]

# Label-independent surface transforms for Vietnamese insertions.
_TEEN = [("mật khẩu", "mk"), ("tài khoản", "tk"), ("cảm ơn", "tks"), ("không", "ko"),
         ("được", "dc"), ("với", "vs")]
VI_TRANSFORM_WEIGHTS = (("plain", 0.75), ("noaccent", 0.15), ("teen", 0.10))


# ----------------------------------------------------------------------------
# Determinism helpers
# ----------------------------------------------------------------------------
def _digest(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def rng_for(seed: int, *parts: Any) -> random.Random:
    """One independent RNG per item, so output does not depend on iteration order."""
    return random.Random(_digest(seed, *parts))


def split_of(key: str, seed: int = 0) -> str:
    """Stable split from a key: the same key always lands in the same split."""
    point = (_digest("split", seed, key) % 10_000) / 10_000
    cut_train, cut_val = SPLIT_RATIOS[0], SPLIT_RATIOS[0] + SPLIT_RATIOS[1]
    return SPLITS[0] if point < cut_train else SPLITS[1] if point < cut_val else SPLITS[2]


# ----------------------------------------------------------------------------
# Seeds
# ----------------------------------------------------------------------------
def load_seeds(seed_dir: str = SEED_DIR) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (attack templates with split assigned, benign bank)."""
    with open(os.path.join(seed_dir, "attack_bank.json"), encoding="utf-8") as handle:
        attack = json.load(handle)
    with open(os.path.join(seed_dir, "benign_bank.json"), encoding="utf-8") as handle:
        benign = json.load(handle)

    templates: List[Dict[str, Any]] = []
    for category, by_lang in attack["categories"].items():
        for lang, sentences in by_lang.items():
            group = [
                {"template_id": f"{category}:{lang}:{i}", "category": category, "lang": lang, "text": s}
                for i, s in enumerate(sentences)
            ]
            if len(group) < 3:
                raise ValueError(f"{category}/{lang} needs at least 3 templates to be split")
            group.sort(key=lambda t: _digest("template", t["template_id"]))
            n = len(group)
            n_val = max(1, round(n * SPLIT_RATIOS[1]))
            n_test = max(1, round(n * SPLIT_RATIOS[2]))
            for pos, tpl in enumerate(group):
                tpl["split"] = "test" if pos < n_test else "validation" if pos < n_test + n_val else "train"
            templates.extend(group)
    return templates, benign


def templates_by_split(templates: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for tpl in templates:
        out.setdefault((tpl["split"], tpl["lang"]), []).append(tpl)
    return out


# ----------------------------------------------------------------------------
# Transforms and insertion
# ----------------------------------------------------------------------------
def pick_transform(rng: random.Random, lang: str) -> str:
    if lang != "vi":
        return "plain"
    roll, acc = rng.random(), 0.0
    for name, weight in VI_TRANSFORM_WEIGHTS:
        acc += weight
        if roll < acc:
            return name
    return "plain"


def apply_transform(text: str, transform: str) -> str:
    if transform == "noaccent":
        return remove_vietnamese_accents(text)
    if transform == "teen":
        for full, short in _TEEN:
            text = re.sub(re.escape(full), short, text, flags=re.IGNORECASE)
        return text
    return text


def choose_template(rng: random.Random, pool: List[Dict[str, Any]], used: set) -> Dict[str, Any]:
    """Pick a template not used yet for this base text, so its two attack variants differ."""
    fresh = [t for t in pool if t["template_id"] not in used]
    tpl = rng.choice(fresh or pool)
    used.add(tpl["template_id"])
    return tpl


def pick_length_matched(rng: random.Random, candidates: List[str], target_len: int, top: int = 3) -> str:
    """Choose a benign sentence whose length is close to the attack it is paired with."""
    ranked = sorted(candidates, key=lambda c: abs(len(c) - target_len))
    return rng.choice(ranked[:top])


_CUT_POINTS = re.compile(r"[.!?]\s|\n")


def insert_sentence(context: str, sentence: str, where: float) -> str:
    """Insert `sentence` inline at a sentence/line boundary chosen by `where` in [0, 1]."""
    cuts = [m.end() for m in _CUT_POINTS.finditer(context)]
    if not cuts:
        return f"{context} {sentence}"
    cut = cuts[min(int(where * len(cuts)), len(cuts) - 1)]
    return f"{context[:cut]}{sentence} {context[cut:]}"


def combine_chat(prompt: str, sentence: str, where: float) -> str:
    return f"{sentence} {prompt}" if where < 0.3 else f"{prompt} {sentence}"


def _lang_of_pair(base_lang: str, insert_lang: str) -> str:
    return base_lang if base_lang == insert_lang else "mixed"


# ----------------------------------------------------------------------------
# Row builders
# ----------------------------------------------------------------------------
def _row(text, label, lang, source, attack_type, orig_id, template_id, variant, split, kind, insert_text=""):
    """`insert_text` is the exact sentence inserted into the base text ('' when nothing was inserted).
    Training needs it to label chunks: a long document is cut into pieces and only the piece that
    contains this sentence is an attack."""
    return {
        "text": text, "label_binary": label, "label": "INJECTION" if label else "SAFE",
        "lang": lang, "source": source, "attack_type": attack_type, "orig_id": orig_id,
        "template_id": template_id, "variant": variant, "split": split,
        "is_synthetic": True, "synthetic_kind": kind, "insert_text": insert_text,
    }


def build_doc_rows(
    contexts: pd.DataFrame,
    tpl_index: Dict[Tuple[str, str], List[Dict[str, Any]]],
    benign: Dict[str, Any],
    seed: int,
    vi_share: float = 0.5,
) -> List[Dict[str, Any]]:
    """contexts: columns intent, context, orig_id, optional lang. Four rows per base: 2 safe, 2 attack."""
    rows: List[Dict[str, Any]] = []
    for item in contexts.itertuples(index=False):
        rng = rng_for(seed, "doc", item.orig_id)
        split = split_of(item.orig_id, seed)
        where = rng.random()
        base_lang = getattr(item, "lang", "en")
        # An English document gets a Vietnamese insertion about half the time (code-switching);
        # a Vietnamese document mostly gets a Vietnamese one.
        p_vi = vi_share if base_lang == "en" else 0.7

        def render(inserted: Optional[str]) -> str:
            context = item.context if inserted is None else insert_sentence(item.context, inserted, where)
            return f"User intent: {item.intent}\nExternal context:\n{context}"

        rows.append(_row(render(None), 0, base_lang, "doc_base", "safe", item.orig_id, "", "clean", split, "base_text"))

        used: set = set()

        def make_attack(index: int):
            lang = "vi" if rng.random() < p_vi else "en"
            tpl = choose_template(rng, tpl_index[(split, lang)], used)
            transform = pick_transform(rng, lang)
            sentence = apply_transform(tpl["text"], transform)
            rows.append(_row(
                render(sentence), 1, _lang_of_pair(base_lang, lang), "doc_base", tpl["category"],
                item.orig_id, tpl["template_id"], f"attack_insert_{index}", split, "template_injection", sentence,
            ))
            return sentence, lang, transform

        first_sentence, first_lang, first_transform = make_attack(1)
        make_attack(2)

        # Benign insert: same language and transform as the first attack, length-matched to it.
        pool = benign["doc_inserts"][first_lang]
        note = apply_transform(pick_length_matched(rng, pool, len(first_sentence)), first_transform)
        rows.append(_row(
            render(note), 0, _lang_of_pair(base_lang, first_lang), "doc_base", "safe", item.orig_id,
            "", "benign_insert", split, "template_injection", note,
        ))
    return rows


def build_chat_rows(
    prompts: pd.DataFrame,
    tpl_index: Dict[Tuple[str, str], List[Dict[str, Any]]],
    benign: Dict[str, Any],
    seed: int,
) -> List[Dict[str, Any]]:
    """prompts: columns text, lang, source, orig_id. Four rows per prompt: 2 safe, 2 attack."""
    rows: List[Dict[str, Any]] = []
    for item in prompts.itertuples(index=False):
        rng = rng_for(seed, "chat", item.orig_id)
        split = split_of(item.orig_id, seed)
        where = rng.random()
        base_lang = item.lang if item.lang in ("en", "vi") else "vi"

        rows.append(_row(item.text, 0, item.lang, item.source, "safe", item.orig_id, "", "clean", split, "base_text"))

        def pick_lang() -> str:
            return base_lang if rng.random() < 0.7 else ("en" if base_lang == "vi" else "vi")

        attacks = []
        used: set = set()
        for index in (1, 2):
            lang = pick_lang()
            tpl = choose_template(rng, tpl_index[(split, lang)], used)
            transform = pick_transform(rng, lang)
            sentence = apply_transform(tpl["text"], transform)
            attacks.append((lang, transform, sentence))
            rows.append(_row(
                combine_chat(item.text, sentence, where), 1, _lang_of_pair(base_lang, lang), item.source,
                tpl["category"], item.orig_id, tpl["template_id"], f"attack_insert_{index}", split, "template_injection",
                sentence,
            ))

        lang, transform, sentence = attacks[0]
        pool = benign["chat_addenda"][lang]
        addendum = apply_transform(pick_length_matched(rng, pool, len(sentence)), transform)
        rows.append(_row(
            combine_chat(item.text, addendum, where), 0, _lang_of_pair(base_lang, lang), item.source, "safe",
            item.orig_id, "", "benign_insert", split, "template_injection", addendum,
        ))
    return rows


def build_pure_attack_rows(templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Each template on its own: a bare attack message, split by the template's own split.
    Same source as the clean chat prompts: bare attacks and bare questions are both short,
    which keeps length from separating the labels inside the chat family.
    """
    return [
        _row(t["text"], 1, t["lang"], "chat_bank", t["category"], f"pure:{t['template_id']}",
             t["template_id"], "pure_attack", t["split"], "template_injection")
        for t in templates
    ]


_TM_ATTACK = {
    "goal hijacking": "direct_injection",
    "prompt leaking": "prompt_leaking",
    "refusal bypass": "jailbreak_roleplay",
    "character/token masking": "obfuscation",
    "encoding/obfuscation": "obfuscation",
    "steganography": "obfuscation",
}
_TM_LANG = {"english": "en", "vietnamese": "vi", "mixed": "mixed"}


def build_tmdeptrai_rows(raw: List[Dict[str, Any]], seed: int) -> List[Dict[str, Any]]:
    """Keep the LLM-generated rows as they are; only normalise labels/lang and assign a split."""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for record in raw:
        text = str(record.get("text", "")).strip()
        key = re.sub(r"\s+", " ", text.lower())
        label_raw = str(record.get("label", "")).strip().upper()
        if not text or key in seen or label_raw not in {"INJECTION", "BENIGN"}:
            continue
        seen.add(key)
        label = 1 if label_raw == "INJECTION" else 0
        orig_id = "tm:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        attack_type = "safe" if label == 0 else _TM_ATTACK.get(str(record.get("attack_type", "")).strip().lower(), "direct_injection")
        lang = _TM_LANG.get(str(record.get("primary_language", "")).strip().lower()) or detect_language(text)
        rows.append(_row(text, label, lang, "tmdeptrai", attack_type, orig_id, "", "raw",
                         split_of(orig_id, seed), "llm_generated"))
    return rows


# ----------------------------------------------------------------------------
# Loading bases
# ----------------------------------------------------------------------------
def load_doc_contexts(path: str, n_docs: int, seed: int) -> pd.DataFrame:
    """Benign BIPIA-GPT contexts only (source 'Generated by GPT-4o-mini'). BIPIA-origin rows are dropped."""
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row.get("label", 1)) != 0:
                continue
            context, intent = str(row.get("context", "")).strip(), str(row.get("user_intent", "")).strip()
            if context and intent:
                records.append({"intent": intent, "context": context})
    frame = pd.DataFrame(records).drop_duplicates(subset=["context"]).reset_index(drop=True)
    frame["orig_id"] = ["doc:" + hashlib.sha1(c.encode("utf-8")).hexdigest()[:12] for c in frame["context"]]
    return frame.sample(n=min(n_docs, len(frame)), random_state=seed).reset_index(drop=True)


def load_chat_prompts(benign: Dict[str, Any], tm_benign: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for lang, prompts in benign["chat_prompts"].items():
        for text in prompts:
            rows.append({"text": text, "lang": lang, "source": "chat_bank"})
    for record in tm_benign:
        text = str(record.get("text", "")).strip()
        lang = _TM_LANG.get(str(record.get("primary_language", "")).strip().lower()) or detect_language(text)
        if text:
            rows.append({"text": text, "lang": lang, "source": "tmdeptrai"})
    frame = pd.DataFrame(rows).drop_duplicates(subset=["text"]).reset_index(drop=True)
    frame["orig_id"] = ["chat:" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:12] for t in frame["text"]]
    return frame


def load_vi_contexts(path: str) -> pd.DataFrame:
    """Vietnamese document bases written by generate_vi.py docs (benign only)."""
    with open(path, "r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    frame = pd.DataFrame(records)[["intent", "context", "orig_id"]].drop_duplicates(subset=["context"])
    frame["lang"] = "vi"
    return frame.reset_index(drop=True)


def _form_stratum(text: str) -> Tuple[bool, bool, int, bool]:
    """
    Surface form that must not predict the label: question mark, digits, length bucket, and whether
    the text is written without diacritics (after label verification, attacks were 18% unaccented
    against 5% for safe messages).
    """
    return ("?" in text, any(c.isdigit() for c in text), len(text) // 20, text == remove_vietnamese_accents(text))


def match_strata(rows: List[Dict[str, Any]], seed: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Make safe and attack rows share the same surface form.

    LLMs do not follow "half questions, a third with numbers" exactly: in the DeepSeek pilot
    safe messages were 37% questions vs 24% for attacks, and style AUC stayed at 0.77. Rows are
    grouped by (has "?", has digit, length // 20, no diacritics); in each group both labels keep the same number
    of rows (chosen deterministically). Costs data, buys a form that cannot reveal the label.
    """
    groups: Dict[Tuple[bool, bool, int, bool], Dict[int, List[Dict[str, Any]]]] = {}
    for row in rows:
        groups.setdefault(_form_stratum(row["text"]), {0: [], 1: []})[int(row["label_binary"])].append(row)
    kept: List[Dict[str, Any]] = []
    for stratum, by_label in groups.items():
        n = min(len(by_label[0]), len(by_label[1]))
        for label in (0, 1):
            ranked = sorted(by_label[label], key=lambda r: _digest("match", seed, r["orig_id"], r["text"]))
            kept.extend(ranked[:n])
    return kept, {"before": len(rows), "after": len(kept), "dropped": len(rows) - len(kept)}


def load_generated_rows(paths: List[str], seed: int, match: bool = True) -> List[Dict[str, Any]]:
    """Rows from generate_vi.py chat / translate. Each keeps its own label and orig_id.
    With `match=True` the two labels are matched on surface form (see match_strata)."""
    rows: List[Dict[str, Any]] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rec = json.loads(line)
                label = int(rec["label_binary"])
                rows.append(_row(
                    rec["text"], label, "vi", "llm_gen_vi", "safe" if label == 0 else rec.get("attack_type", "direct_injection"),
                    rec["orig_id"], "", rec.get("variant", "raw"), split_of(rec["orig_id"], seed), rec.get("synthetic_kind", "llm_generated"),
                ))
    if match and rows:
        rows, report = match_strata(rows, seed)
        print(f"[INFO] matched generated rows on surface form: kept {report['after']} of {report['before']}")
    return rows


EXTERNAL_TEST_PATH = os.path.join(BASE_DIR, "data", "eval", "tmdeptrai_external_test.csv")


def build_external_test(test_records: List[Dict[str, Any]], train_records: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    The author's own test split, kept OUT of training. Its author is not us (different
    generator, different person), so it measures generalisation beyond our seed banks.
    Rows whose text also appears in training are dropped.
    """
    train_keys = {re.sub(r"\s+", " ", str(r.get("text", "")).strip().lower()) for r in train_records}
    rows = build_tmdeptrai_rows(test_records, seed=0)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    keys = frame["text"].map(lambda t: re.sub(r"\s+", " ", t.strip().lower()))
    frame = frame[~keys.isin(train_keys)].reset_index(drop=True)
    frame["source"] = "tmdeptrai_test"
    frame["split"] = "external_test"
    return frame


def fetch_tmdeptrai(files: Tuple[str, ...] = ("train.jsonl",)) -> List[Dict[str, Any]]:
    """Training records by default. The author's test.jsonl is fetched separately (see build_external_test)."""
    from huggingface_hub import hf_hub_download

    records: List[Dict[str, Any]] = []
    for name in files:
        path = hf_hub_download("tmdeptrai3012/prompt-injection-dataset-vi-en", name, repo_type="dataset")
        with open(path, "r", encoding="utf-8") as handle:
            records.extend(json.loads(line) for line in handle if line.strip())
    return records


# ----------------------------------------------------------------------------
# Validation and build
# ----------------------------------------------------------------------------
def validate_dataset(frame: pd.DataFrame) -> List[str]:
    """Hard invariants. An empty list means the dataset is structurally sound."""
    problems: List[str] = []
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        return [f"missing columns: {missing}"]
    if frame["text"].astype(str).str.strip().eq("").any():
        problems.append("empty text")
    if not set(frame["label_binary"].unique()) <= {0, 1}:
        problems.append("label_binary has values other than 0/1")
    if not set(frame["split"].unique()) <= set(SPLITS):
        problems.append("unknown split value")

    by_orig = frame.groupby("orig_id")["split"].nunique()
    if (by_orig > 1).any():
        problems.append(f"{int((by_orig > 1).sum())} orig_id values appear in more than one split")

    templated = frame[frame["template_id"].astype(str) != ""]
    by_tpl = templated.groupby("template_id")["split"].nunique()
    if (by_tpl > 1).any():
        problems.append(f"{int((by_tpl > 1).sum())} attack templates appear in more than one split")

    attacks = frame[frame["label_binary"] == 1]
    if (attacks["attack_type"] == "safe").any():
        problems.append("an attack row has attack_type 'safe'")
    if (frame[frame["label_binary"] == 0]["attack_type"] != "safe").any():
        problems.append("a safe row has an attack_type")

    paired = frame[frame["variant"].isin(["clean", "benign_insert"]) | frame["variant"].str.startswith("attack_insert")]
    counts = paired.groupby("orig_id")["label_binary"].agg(["min", "max"])
    if ((counts["min"] == 1) | (counts["max"] == 0)).any():
        problems.append("a base text lacks either its safe or its attack variant (pair integrity)")
    return problems


def balance_labels(frame: pd.DataFrame, seed: int = 0) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Equalise safe/attack counts inside every (split, language) group.

    Without this, language itself predicts the label: the `clean` variant never has an
    inserted sentence, so it is always English, and "mixed" text ends up mostly attacks.
    Rows are dropped from the surplus label only, least valuable first, and never so that a
    base text loses its last safe or last attack variant (pair integrity is preserved).
    """
    keep = pd.Series(True, index=frame.index)
    paired = frame["variant"].isin(["clean", "benign_insert", "attack_insert_1", "attack_insert_2"])
    drop_order = {1: ["attack_insert_2", "pure_attack", "translated", "raw", "attack_insert_1"],
                  0: ["clean", "translated", "raw", "benign_insert"]}
    report: Dict[str, Any] = {"dropped": 0, "residual_imbalance": {}}

    for (split, lang), group in frame.groupby(["split", "lang"]):
        counts = group["label_binary"].value_counts()
        n0, n1 = int(counts.get(0, 0)), int(counts.get(1, 0))
        if n0 == n1:
            continue
        surplus_label = 1 if n1 > n0 else 0
        to_drop = abs(n1 - n0)
        remaining = {oid: int(c) for oid, c in
                     frame[paired & (frame["label_binary"] == surplus_label)].groupby("orig_id").size().items()}
        candidates = group[group["label_binary"] == surplus_label].copy()
        candidates["_rank"] = candidates["variant"].map(
            {v: i for i, v in enumerate(drop_order[surplus_label])}).fillna(len(drop_order[surplus_label]))
        candidates["_h"] = [_digest("balance", seed, o, v) for o, v in zip(candidates["orig_id"], candidates["variant"])]
        for idx, row in candidates.sort_values(["_rank", "_h"]).iterrows():
            if to_drop == 0:
                break
            if paired.loc[idx]:
                if remaining.get(row["orig_id"], 0) <= 1:
                    continue  # would orphan the base text from this label
                remaining[row["orig_id"]] -= 1
            keep.loc[idx] = False
            to_drop -= 1
            report["dropped"] += 1
        if to_drop:
            report["residual_imbalance"][f"{split}/{lang}"] = to_drop
    return frame[keep].reset_index(drop=True), report


def assemble(
    contexts: Optional[pd.DataFrame],
    tm_records: List[Dict[str, Any]],
    templates: List[Dict[str, Any]],
    benign: Dict[str, Any],
    seed: int = 0,
    include_pure: bool = True,
    generated_rows: Optional[List[Dict[str, Any]]] = None,
    balance: bool = True,
) -> pd.DataFrame:
    tpl_index = templates_by_split(templates)
    rows: List[Dict[str, Any]] = []
    if contexts is not None and len(contexts):
        rows += build_doc_rows(contexts, tpl_index, benign, seed)
    tm_benign = [r for r in tm_records if str(r.get("label", "")).strip().upper() == "BENIGN"]
    rows += build_chat_rows(load_chat_prompts(benign, tm_benign), tpl_index, benign, seed)
    if include_pure:
        rows += build_pure_attack_rows(templates)
    rows += build_tmdeptrai_rows(tm_records, seed)
    rows += generated_rows or []
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame = frame.drop_duplicates(subset=["text", "label_binary"]).reset_index(drop=True)
    if balance:
        frame, report = balance_labels(frame, seed)
        frame.attrs["balance_report"] = report
    return frame


def l1_coverage(templates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How many attack templates the regex layer already catches (the rest need the classifier)."""
    from firewall.layer1 import Layer1Prefilter

    l1 = Layer1Prefilter(use_vector=False)
    caught = {t["template_id"]: l1.check(t["text"])["decision"] == "BLOCK" for t in templates}
    by_split: Dict[str, Dict[str, int]] = {}
    for t in templates:
        slot = by_split.setdefault(t["split"], {"templates": 0, "caught_by_regex": 0})
        slot["templates"] += 1
        slot["caught_by_regex"] += int(caught[t["template_id"]])
    total = sum(caught.values())
    return {"templates": len(templates), "caught_by_regex": total,
            "share_needing_classifier": round(1 - total / len(templates), 3), "by_split": by_split}


def write_outputs(frame: pd.DataFrame, templates: List[Dict[str, Any]], args: argparse.Namespace) -> Dict[str, Any]:
    from data.scripts import audit_leakage as audit

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    for split in SPLITS:
        frame[frame["split"] == split].to_csv(os.path.join(args.out_dir, f"dataset_v2_{split}.csv"), index=False)

    audit_view = frame.rename(columns={"source": "source_name"}).assign(source="dataset_v2")
    manifest: Dict[str, Any] = {
        "seed": args.seed,
        "n_rows": int(len(frame)),
        "rows_by_split": {k: int(v) for k, v in frame["split"].value_counts().items()},
        "label_by_split": {s: {str(k): int(v) for k, v in g["label_binary"].value_counts().items()}
                           for s, g in frame.groupby("split")},
        "rows_by_source": {k: int(v) for k, v in frame["source"].value_counts().items()},
        "rows_by_lang": {k: int(v) for k, v in frame["lang"].value_counts().items()},
        "dataset_sha256": audit.dataset_hash(audit_view),
        "balance": frame.attrs.get("balance_report"),
        "label_by_split_and_lang": {f"{sp}/{lg}": {str(k): int(v) for k, v in g["label_binary"].value_counts().items()}
                                    for (sp, lg), g in frame.groupby(["split", "lang"])},
        "validation_problems": validate_dataset(frame),
        "regex_coverage_of_templates": l1_coverage(templates),
        "audit": {"all": audit.audit_frame(audit_view, "dataset_v2")},
    }
    for split in SPLITS:
        part = audit_view[audit_view["split"] == split]
        manifest["audit"][split] = audit.audit_frame(part, f"dataset_v2:{split}")
    for source, part in audit_view.groupby("source_name"):
        manifest["audit"][f"source:{source}"] = audit.audit_frame(part, f"dataset_v2:{source}")
    manifest["leaky_parts"] = [k for k, v in manifest["audit"].items() if v["leaky"]]

    with open(os.path.join(RESULTS_DIR, "dataset_v2_audit.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bipia-jsonl", default=DEFAULT_BIPIA)
    parser.add_argument("--n-docs", type=int, default=3000, help="document bases to build (4 rows each)")
    parser.add_argument("--no-tmdeptrai", action="store_true", help="skip the tmdeptrai3012 source (offline)")
    parser.add_argument("--vi-contexts", help="jsonl from generate_vi.py docs: Vietnamese document bases")
    parser.add_argument("--generated", action="append", default=[],
                        help="jsonl from generate_vi.py chat/translate (repeatable)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--strict", action="store_true", help="exit 1 if any part of the dataset is flagged leaky")
    args = parser.parse_args()

    templates, benign = load_seeds()
    contexts = load_doc_contexts(args.bipia_jsonl, args.n_docs, args.seed) if os.path.exists(args.bipia_jsonl) else None
    if contexts is None:
        print(f"[WARN] {args.bipia_jsonl} not found: building without document bases.")
    tm_records = [] if args.no_tmdeptrai else fetch_tmdeptrai()
    if tm_records:
        external = build_external_test(fetch_tmdeptrai(("test.jsonl",)), tm_records)
        os.makedirs(os.path.dirname(EXTERNAL_TEST_PATH), exist_ok=True)
        external.to_csv(EXTERNAL_TEST_PATH, index=False)
        print(f"[INFO] {len(external)} external test rows (tmdeptrai test.jsonl, never trained on) -> {EXTERNAL_TEST_PATH}")
    if args.vi_contexts:
        vi_frame = load_vi_contexts(args.vi_contexts)
        contexts = vi_frame if contexts is None else pd.concat([contexts.assign(lang="en"), vi_frame], ignore_index=True)

    frame = assemble(contexts, tm_records, templates, benign, seed=args.seed,
                     generated_rows=load_generated_rows(args.generated, args.seed))
    manifest = write_outputs(frame, templates, args)

    print(f"[INFO] rows={manifest['n_rows']} splits={manifest['rows_by_split']}")
    print(f"[INFO] sources={manifest['rows_by_source']} langs={manifest['rows_by_lang']}")
    print(f"[INFO] regex already catches {manifest['regex_coverage_of_templates']['caught_by_regex']}/"
          f"{manifest['regex_coverage_of_templates']['templates']} attack templates")
    print(f"[INFO] validation problems: {manifest['validation_problems'] or 'none'}")
    print(f"[INFO] leaky parts: {manifest['leaky_parts'] or 'none'}")
    if manifest["validation_problems"] or (args.strict and manifest["leaky_parts"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
