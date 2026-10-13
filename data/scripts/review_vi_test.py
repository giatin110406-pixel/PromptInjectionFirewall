"""
Blind cross-review of the Vietnamese test set.

The test set was drafted by Claude, so its labels are only as good as an independent human
check. This tool splits the rows among the reviewers so each person labels about 1/N of the
set WITHOUT seeing the author's label, then merges the answers back.

    # 1. Split: one sheet per reviewer, labels hidden
    python data/scripts/review_vi_test.py split --reviewers An,Binh,Chi,Dung,Em,Phuc

    # 2. Each reviewer opens data/eval/review/review_<name>.csv and fills `reviewer_label`
    #    with benign or attack for every row (nothing else needs editing).

    # 3. Merge: fills reviewer / reviewer_label in vi_test_v1.csv and lists disagreements
    python data/scripts/review_vi_test.py merge
    python data/scripts/review_vi_test.py merge --drop-disagreements   # remove ambiguous rows

A row is reviewed by exactly one person, and the reviewer is never the author.
"""
import argparse
import csv
import os
import random
import re
import shutil
import sys
from typing import Dict, List, Tuple

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_FILE = os.path.join(BASE_DIR, "data", "eval", "vi_test_v1.csv")
DEFAULT_DIR = os.path.join(BASE_DIR, "data", "eval", "review")
SHEET_COLUMNS = ["id", "text", "reviewer_label", "notes"]
LABELS = {"benign", "attack"}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())


def load(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def split(path: str, reviewers: List[str], out_dir: str, seed: int = 0) -> Dict[str, int]:
    """Write one blind sheet per reviewer. Returns rows per reviewer."""
    frame = load(path)
    names = [r.strip() for r in reviewers if r.strip()]
    if len(names) < 2:
        raise ValueError("need at least two reviewers so nobody reviews all rows alone")
    if len({_slug(n).lower() for n in names}) != len(names):
        raise ValueError("reviewer names must be distinct")

    eligible = frame[frame["author"].str.upper() != "EXAMPLE"]
    order = list(eligible.index)
    random.Random(seed).shuffle(order)

    buckets: Dict[str, List[int]] = {n: [] for n in names}
    for position, index in enumerate(order):
        # round robin, skipping a reviewer who is the author of that row
        for step in range(len(names)):
            name = names[(position + step) % len(names)]
            if name.lower() != str(frame.loc[index, "author"]).strip().lower():
                buckets[name].append(index)
                break

    os.makedirs(out_dir, exist_ok=True)
    counts: Dict[str, int] = {}
    for name, indices in buckets.items():
        sheet = os.path.join(out_dir, f"review_{_slug(name)}.csv")
        with open(sheet, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(SHEET_COLUMNS)
            for index in sorted(indices):  # original order: no label-correlated ordering to exploit
                writer.writerow([frame.loc[index, "id"], frame.loc[index, "text"], "", ""])
        counts[name] = len(indices)
    return counts


def _read_sheets(directory: str) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    """id -> (reviewer name, reviewer_label). Also returns problems found while reading."""
    answers: Dict[str, Tuple[str, str]] = {}
    problems: List[str] = []
    for filename in sorted(os.listdir(directory)):
        match = re.fullmatch(r"review_(.+)\.csv", filename)
        if not match:
            continue
        reviewer = match.group(1).replace("_", " ").strip()
        sheet = load(os.path.join(directory, filename))
        missing_columns = [c for c in ("id", "reviewer_label") if c not in sheet.columns]
        if missing_columns:
            problems.append(f"{filename}: missing columns {missing_columns}")
            continue
        for row in sheet.itertuples(index=False):
            label = str(row.reviewer_label).strip().lower()
            if label == "":
                problems.append(f"{filename}: row {row.id} has no reviewer_label")
            elif label not in LABELS:
                problems.append(f"{filename}: row {row.id} has label '{label}' (use benign or attack)")
            elif row.id in answers:
                problems.append(f"{filename}: row {row.id} was already reviewed by {answers[row.id][0]}")
            else:
                answers[row.id] = (reviewer, label)
    return answers, problems


def merge(path: str, directory: str, drop_disagreements: bool = False) -> Dict[str, object]:
    frame = load(path)
    answers, problems = _read_sheets(directory)

    unknown = sorted(set(answers) - set(frame["id"]))
    if unknown:
        problems.append(f"sheets contain ids that are not in the test set: {unknown[:5]}")
    backup = os.path.join(os.path.dirname(path), "vi_test_v1.before_review.csv")
    if not os.path.exists(backup):
        shutil.copyfile(path, backup)  # keep the author's untouched version for provenance

    reviewed = frame["id"].isin(answers)
    frame.loc[reviewed, "reviewer"] = frame.loc[reviewed, "id"].map(lambda i: answers[i][0])
    frame.loc[reviewed, "reviewer_label"] = frame.loc[reviewed, "id"].map(lambda i: answers[i][1])

    disagree = reviewed & (frame["label"].str.lower() != frame["reviewer_label"].str.lower())
    dropped = frame[disagree]
    if drop_disagreements and len(dropped):
        dropped.to_csv(os.path.join(directory, "dropped_disagreements.csv"), index=False, encoding="utf-8-sig")
        frame = frame[~disagree]
    frame.to_csv(path, index=False, encoding="utf-8-sig")

    return {
        "rows_total": int(len(frame) + (len(dropped) if drop_disagreements else 0)),
        "reviewed": int(reviewed.sum()),
        "unreviewed": int((~reviewed).sum()),
        "agree": int(reviewed.sum() - disagree.sum()),
        "disagree": int(disagree.sum()),
        "agreement_rate": round(float(1 - disagree.sum() / max(int(reviewed.sum()), 1)), 3),
        "disagreement_ids": list(dropped["id"]) if len(dropped) else [],
        "dropped": bool(drop_disagreements),
        "problems": problems,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_split = sub.add_parser("split", help="write one blind review sheet per reviewer")
    p_split.add_argument("--reviewers", required=True, help="comma-separated names, e.g. An,Binh,Chi")
    p_split.add_argument("--file", default=DEFAULT_FILE)
    p_split.add_argument("--out-dir", default=DEFAULT_DIR)
    p_split.add_argument("--seed", type=int, default=0)
    p_merge = sub.add_parser("merge", help="merge filled sheets back into the test set")
    p_merge.add_argument("--file", default=DEFAULT_FILE)
    p_merge.add_argument("--dir", default=DEFAULT_DIR)
    p_merge.add_argument("--drop-disagreements", action="store_true",
                         help="remove rows where reviewer and author disagree (ambiguous); saved separately")
    args = parser.parse_args()

    if args.command == "split":
        counts = split(args.file, args.reviewers.split(","), args.out_dir, args.seed)
        for name, n in counts.items():
            print(f"[INFO] {name}: {n} rows -> {os.path.join(args.out_dir, 'review_' + _slug(name) + '.csv')}")
        print("[INFO] Reviewers: do NOT look at data/eval/vi_test_v1.csv. Fill only the reviewer_label column.")
    else:
        result = merge(args.file, args.dir, args.drop_disagreements)
        for key, value in result.items():
            if key != "problems":
                print(f"[INFO] {key}: {value}")
        for problem in result["problems"]:
            print(f"[WARN] {problem}")
        if result["disagree"] and not args.drop_disagreements:
            print("[ACTION] discuss the disagreements: fix the text, or rerun with --drop-disagreements to remove them.")
        sys.exit(1 if result["problems"] else 0)


if __name__ == "__main__":
    main()
