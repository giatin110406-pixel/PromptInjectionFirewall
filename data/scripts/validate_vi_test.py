"""
Validate the human-written Vietnamese test set (P2-T3).

The test set is the only trustworthy measure of Vietnamese quality, so this checks that it
cannot be flattered by the training data and cannot be solved by shortcuts:

  errors (exit code 1)
    - schema, labels, attack types, authors and reviewers filled in
    - reviewer is a different person from the author
    - duplicate texts, texts that also appear in the training/seed data
    - fewer than the required rows or per-class rows
  warnings
    - the reviewer disagrees with the author's label (list them, discuss, fix)
    - length separates the labels (a model could pass by guessing on length)
    - style quotas not met (no-accent, teencode, mixed, hard negatives, subtle attacks)
    - text that looks like a phone number, e-mail or national ID

Rows whose author is EXAMPLE (the ones in the template) are ignored.

Usage:
    python data/scripts/validate_vi_test.py
    python data/scripts/validate_vi_test.py --file data/eval/vi_test_v1.csv --min-rows 300
"""
import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts import audit_leakage as audit  # noqa: E402
from data.scripts.generate_vi import looks_vietnamese  # noqa: E402

DEFAULT_FILE = os.path.join(BASE_DIR, "data", "eval", "vi_test_v1.csv")
RESULT_PATH = os.path.join(BASE_DIR, "evaluation", "results", "vi_test_validation.json")
TRAIN_FILES = [os.path.join(BASE_DIR, "data", "processed", f"dataset_v2_{s}.csv") for s in ("train", "validation")]

REQUIRED = ["id", "text", "label", "attack_type", "style", "difficulty", "author", "reviewer", "reviewer_label"]
ATTACK_TYPES = {"direct_injection", "prompt_leaking", "privilege_escalation", "jailbreak_roleplay",
                "action_abuse", "data_exfiltration", "subtle_redirect", "obfuscation"}
STYLES = {"plain", "noaccent", "teencode", "mixed"}
LABELS = {"benign": 0, "attack": 1, "0": 0, "1": 1}

MIN_ROWS = 300
MIN_PER_CLASS = 120
LENGTH_AUC_WARN = 0.70
STYLE_QUOTAS = {"noaccent_or_teencode": 0.15, "mixed": 0.10}  # share of rows
MIN_HARD_NEGATIVES = 0.08   # share of benign rows with difficulty=hard
MIN_SUBTLE_ATTACKS = 0.08   # share of attack rows with difficulty=hard

_PII = [("phone", re.compile(r"(?<!\d)0\d{9,10}(?!\d)")), ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
        ("national_id", re.compile(r"(?<!\d)\d{12}(?!\d)"))]
# Placeholder domains used in attack examples are fine.
_PII_ALLOWED = re.compile(r"@[\w.-]*\.example\b", re.IGNORECASE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def load_reference(paths: List[str]) -> Optional[pd.DataFrame]:
    frames = [pd.read_csv(p, usecols=["text"]) for p in paths if os.path.exists(p)]
    return pd.concat(frames, ignore_index=True) if frames else None


def validate(frame: pd.DataFrame, reference: Optional[pd.DataFrame] = None, min_rows: int = MIN_ROWS,
             min_per_class: int = MIN_PER_CLASS) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        return {"ok": False, "errors": [f"missing columns: {missing}"], "warnings": [], "stats": {}}

    rows = frame[frame["author"].astype(str).str.strip().str.upper() != "EXAMPLE"].copy()
    rows = rows.dropna(subset=["text"]).reset_index(drop=True)
    if rows.empty:
        return {"ok": False, "errors": ["no real rows (only EXAMPLE rows or empty file)"], "warnings": [], "stats": {}}

    for col in ("text", "author", "reviewer"):
        rows[col] = rows[col].astype(str).str.strip()
    rows["label_binary"] = rows["label"].astype(str).str.strip().str.lower().map(LABELS)
    rows["reviewer_binary"] = rows["reviewer_label"].astype(str).str.strip().str.lower().map(LABELS)

    if rows["label_binary"].isna().any():
        errors.append(f"{int(rows['label_binary'].isna().sum())} rows have a label other than benign/attack")
        rows = rows.dropna(subset=["label_binary"])
    rows["label_binary"] = rows["label_binary"].astype(int)

    bad_types = rows[(rows["label_binary"] == 1) & ~rows["attack_type"].isin(ATTACK_TYPES)]
    if len(bad_types):
        errors.append(f"{len(bad_types)} attack rows have an unknown attack_type (ids: {list(bad_types['id'])[:5]})")
    wrong_safe = rows[(rows["label_binary"] == 0) & (rows["attack_type"].astype(str).str.lower() != "safe")]
    if len(wrong_safe):
        errors.append(f"{len(wrong_safe)} benign rows must have attack_type 'safe' (ids: {list(wrong_safe['id'])[:5]})")
    bad_style = rows[~rows["style"].isin(STYLES)]
    if len(bad_style):
        errors.append(f"{len(bad_style)} rows have an unknown style (allowed: {sorted(STYLES)})")

    bad_difficulty = rows[~rows["difficulty"].isin(["easy", "hard"])]
    if len(bad_difficulty):
        errors.append(f"{len(bad_difficulty)} rows have difficulty other than easy/hard")

    if (rows["author"].isin(["", "nan"])).any():
        errors.append("some rows have no author")
    if (rows["reviewer"].isin(["", "nan"])).any():
        errors.append(f"{int(rows['reviewer'].isin(['', 'nan']).sum())} rows have no reviewer yet")
    same = rows[(rows["author"].str.lower() == rows["reviewer"].str.lower()) & ~rows["reviewer"].isin(["", "nan"])]
    if len(same):
        errors.append(f"{len(same)} rows were reviewed by their own author")

    disagree = rows[rows["reviewer_binary"].notna() & (rows["reviewer_binary"] != rows["label_binary"])]
    if len(disagree):
        warnings.append(f"{len(disagree)} rows where the reviewer disagrees with the author (ids: {list(disagree['id'])[:10]})")

    keys = rows["text"].map(_norm)
    dups = rows[keys.duplicated(keep=False)]
    if len(dups):
        errors.append(f"{len(dups)} rows are duplicates of each other (ids: {list(dups['id'])[:10]})")

    if len(rows) < min_rows:
        errors.append(f"only {len(rows)} rows, need at least {min_rows}")
    counts = rows["label_binary"].value_counts()
    for label, name in ((0, "benign"), (1, "attack")):
        if counts.get(label, 0) < min_per_class:
            errors.append(f"only {int(counts.get(label, 0))} {name} rows, need at least {min_per_class}")

    not_vi = rows[~rows["text"].map(looks_vietnamese)]
    if len(not_vi):
        warnings.append(f"{len(not_vi)} rows do not look Vietnamese (ids: {list(not_vi['id'])[:10]})")

    for name, pattern in _PII:
        hits = rows[rows["text"].map(lambda t: bool(pattern.search(_PII_ALLOWED.sub("", t))))]
        if len(hits):
            warnings.append(f"{len(hits)} rows look like they contain a {name}: remove real personal data (ids: {list(hits['id'])[:5]})")

    overlap = None
    if reference is not None and len(reference):
        ref_keys = {_norm(t) for t in reference["text"]}
        exact = rows[keys.isin(ref_keys)]
        if len(exact):
            errors.append(f"{len(exact)} test rows also appear in the training/seed data (ids: {list(exact['id'])[:10]})")
        view = rows.assign(source="vi_test")[["text", "label_binary", "source"]]
        overlap = audit.overlap_with_reference(view, reference)
        if overlap["near_duplicate_rate"] >= 0.05:
            warnings.append(f"{overlap['near_duplicate_rate']:.0%} of test rows are near-duplicates of training text")
    else:
        warnings.append("training data not found: overlap with training data was NOT checked")

    view = rows[["text", "label_binary"]]
    length_auc = audit.length_auc(view)
    if length_auc is not None and length_auc >= LENGTH_AUC_WARN:
        warnings.append(f"length separates the labels (AUC {length_auc:.2f}): write benign and attack messages of similar length")

    style_share = {
        "noaccent_or_teencode": float(rows["style"].isin(["noaccent", "teencode"]).mean()),
        "mixed": float((rows["style"] == "mixed").mean()),
    }
    for key, minimum in STYLE_QUOTAS.items():
        if style_share[key] < minimum:
            warnings.append(f"style '{key}' is {style_share[key]:.0%} of rows, target at least {minimum:.0%}")
    hard_neg = float(((rows["label_binary"] == 0) & (rows["difficulty"] == "hard")).sum() / max(counts.get(0, 0), 1))
    subtle = float(((rows["label_binary"] == 1) & (rows["difficulty"] == "hard")).sum() / max(counts.get(1, 0), 1))
    if hard_neg < MIN_HARD_NEGATIVES:
        warnings.append(f"hard benign rows are {hard_neg:.0%} of benign, target at least {MIN_HARD_NEGATIVES:.0%}")
    if subtle < MIN_SUBTLE_ATTACKS:
        warnings.append(f"hard (subtle) attack rows are {subtle:.0%} of attacks, target at least {MIN_SUBTLE_ATTACKS:.0%}")

    stats = {
        "rows": int(len(rows)),
        "label_counts": {str(k): int(v) for k, v in counts.items()},
        "per_author": {k: int(v) for k, v in rows["author"].value_counts().items()},
        "per_attack_type": {k: int(v) for k, v in rows[rows["label_binary"] == 1]["attack_type"].value_counts().items()},
        "per_style": {k: int(v) for k, v in rows["style"].value_counts().items()},
        "length_auc": None if length_auc is None else round(length_auc, 3),
        "overlap_with_training": overlap,
        "style_share": {k: round(v, 3) for k, v in style_share.items()},
        "hard_benign_share": round(hard_neg, 3),
        "hard_attack_share": round(subtle, 3),
    }
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--min-rows", type=int, default=MIN_ROWS)
    parser.add_argument("--min-per-class", type=int, default=MIN_PER_CLASS)
    parser.add_argument("--out", default=RESULT_PATH)
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[ERROR] {args.file} does not exist. Copy data/eval/vi_test_v1_template.csv to that name and fill it in.")
        sys.exit(1)
    frame = pd.read_csv(args.file, dtype=str, keep_default_na=False)
    result = validate(frame, load_reference(TRAIN_FILES), args.min_rows, args.min_per_class)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    for message in result["errors"]:
        print(f"[ERROR] {message}")
    for message in result["warnings"]:
        print(f"[WARN] {message}")
    print("[OK] test set is valid" if result["ok"] else "[FAIL] fix the errors above")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
