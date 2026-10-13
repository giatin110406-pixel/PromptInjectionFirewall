"""
Effect of the consensus policy on the evaluation sets (no model needed: it replays results/l3/records.jsonl).

    python PrepareForBCTĐ2/tools/eval_soft_block.py

Before: a text is blocked when Layer 1 blocks or Layer 2's score reaches the threshold (0.6659).
After:  Layer 1 block -> BLOCK; Layer 2 score >= 0.98 -> BLOCK; 0.6659 <= score < 0.98 with no Layer 1 agreement -> REVIEW
        (held, not blocked); otherwise ALLOW. No LLM judge in either case.
CAUTION: the 0.98 line (the judge's upper edge) was chosen while looking at the score distribution of ALL six sets,
dev and test together, so the test-set numbers here are optimistic, not an independent measurement.
Writes results/soft_block_eval.json.
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECORDS = os.path.join(ROOT, "PrepareForBCTĐ2", "results", "l3", "records.jsonl")
OUT = os.path.join(ROOT, "PrepareForBCTĐ2", "results", "soft_block_eval.json")
THRESHOLD, SOFT = 0.6659, 0.98
GROUPS = {"test sets (dataset_v2 test + external test + vi_test)": ["test", "external_test", "vi_test"],
          "dev sets (validation + external dev + vi_dev)": ["validation", "external_dev", "vi_dev"],
          "all six sets": ["validation", "external_dev", "vi_dev", "test", "external_test", "vi_test"]}


def decide(row, soft: bool) -> str:
    if row["l1"] == "BLOCK":
        return "BLOCK"
    score = row["score"] if row["score"] == row["score"] and row["score"] is not None else 0.0     # NaN-safe
    if score >= THRESHOLD:
        return "REVIEW" if soft and score < SOFT else "BLOCK"
    return "ALLOW"


def counts(frame, label, soft):
    d = frame[frame.label == label].apply(lambda r: decide(r, soft), axis=1)
    return {k: int((d == k).sum()) for k in ("BLOCK", "REVIEW", "ALLOW")}


def main() -> None:
    rows = pd.DataFrame([json.loads(line) for line in open(RECORDS, encoding="utf-8") if line.strip()])
    report = {}
    for name, sets in GROUPS.items():
        frame = rows[rows["set"].isin(sets)]
        entry = {"safe_texts": int((frame.label == 0).sum()), "attacks": int((frame.label == 1).sum())}
        for tag, soft in (("before", False), ("after", True)):
            entry[tag] = {"safe": counts(frame, 0, soft), "attacks": counts(frame, 1, soft)}
        report[name] = entry
        s0, s1, a0, a1 = entry["before"]["safe"], entry["after"]["safe"], entry["before"]["attacks"], entry["after"]["attacks"]
        print(f"{name}\n  safe ({entry['safe_texts']}):    hard-blocked {s0['BLOCK']} -> {s1['BLOCK']}, held for review {s1['REVIEW']}"
              f"\n  attacks ({entry['attacks']}): hard-blocked {a0['BLOCK']} -> {a1['BLOCK']}, held for review {a1['REVIEW']}, allowed {a0['ALLOW']} -> {a1['ALLOW']}")
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
