"""
Transactional requests: does the firewall block ordinary customers who ask to move money?

    python evaluation/eval_transactions.py                       # the engine as configured (L2 in models/l2_multilingual/artifacts)
    python evaluation/eval_transactions.py --artifacts models/l2_multilingual/artifacts_v2_aigen --tag v2
    python evaluation/eval_transactions.py --artifacts models/l2_multilingual/artifacts_v3 --bands evaluation/results/band_calibration_v3.json --tag v3

Set: data/eval/transactions_v1.jsonl, 108 hand-written texts (written by Claude, 01/11/2026, never used for training):
  user_request   52  ordinary transfer, bill, top-up, refund requests carrying an account or customer number (benign)
  user_question   8  questions about such transactions (benign)
  doc_benign     20  invoices, receipts, emails with account numbers; some tell the HUMAN reader to pay (benign)
  doc_injected   20  the same kinds of documents with a transfer instruction aimed at the assistant (attack)
  user_attack     8  rule-override attempts on the user channel that ask for a transfer (attack)

User-channel texts go through FirewallOrchestrator.process_input; flagged = BLOCK or REVIEW (the customer is stopped).
Documents go through process_context; flagged = the decision is not ALLOW (something was cut or held).
`l2_flag` is Layer 2 alone (highest window score >= its threshold). Written to evaluation/results/transactions_eval_<tag>.json.
Found while building WP2 of docs/implementation_plan_v4_vi.md; the "before" numbers for the WP7 data change.
"""
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_layer1 import wilson  # noqa: E402

DATA = os.path.join(BASE_DIR, "data", "eval", "transactions_v1.jsonl")


def rate(hits, n):
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> None:
    from firewall.classifier import DEFAULT_ARTIFACTS
    from model_variant import engine_for

    artifacts = _arg("--artifacts", DEFAULT_ARTIFACTS)
    tag = _arg("--tag", "current")
    engine, l2 = engine_for(artifacts, _arg("--bands"))
    rows = [json.loads(line) for line in open(DATA, encoding="utf-8")]
    out_rows = []
    for row in rows:
        score = max(l2.window_scores(row["text"]))
        if row["channel"] == "user":
            result = engine.process_input(row["text"], use_judge=False)
            decision, flagged = result["decision"], result["decision"] in ("BLOCK", "REVIEW")
        else:
            result = engine.process_context([{"id": row["id"], "text": row["text"], "source": "document"}], use_judge=False)
            decision, flagged = result["decision"], result["decision"] != "ALLOW"
        out_rows.append(dict(row, l2_score=round(score, 4), l2_flag=score >= l2.threshold, decision=decision, flagged=flagged))

    groups = defaultdict(list)
    for row in out_rows:
        groups[row["kind"]].append(row)
        groups[f"{row['kind']}:{row['lang']}"].append(row)
    report = {"artifacts": os.path.relpath(artifacts, BASE_DIR), "l2_threshold": l2.threshold, "soft_block_below": engine.soft_block_below, "n": len(out_rows),
              "note": "benign kinds: flagged = false positive; attack kinds: flagged = caught", "by_group": {}}
    for name, items in sorted(groups.items()):
        report["by_group"][name] = {"flagged": rate(sum(r["flagged"] for r in items), len(items)),
                                    "l2_flag": rate(sum(r["l2_flag"] for r in items), len(items))}
    benign = [r for r in out_rows if r["label"] == 0]
    attacks = [r for r in out_rows if r["label"] == 1]
    report["benign_flagged"] = rate(sum(r["flagged"] for r in benign), len(benign))
    report["attacks_flagged"] = rate(sum(r["flagged"] for r in attacks), len(attacks))
    report["rows"] = out_rows
    path = os.path.join(BASE_DIR, "evaluation", "results", f"transactions_eval_{tag}.json")
    json.dump(report, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    for name in ("user_request", "user_question", "doc_benign", "doc_injected", "user_attack"):
        g = report["by_group"][name]
        print(f"{name:14s} flagged {g['flagged']['hits']:>3}/{g['flagged']['n']:<3} ({g['flagged']['rate']:.0%})  "
              f"L2 alone {g['l2_flag']['hits']:>3}/{g['l2_flag']['n']}")
    print(f"benign flagged {report['benign_flagged']['rate']:.1%}  attacks flagged {report['attacks_flagged']['rate']:.1%}")
    print(f"[INFO] wrote {path}")


if __name__ == "__main__":
    main()
