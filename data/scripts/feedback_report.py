"""
Summarise the feedback collected in the console and turn it into training seeds and a regression check.

    python data/scripts/feedback_report.py                  # counts by kind, layer, language
    python data/scripts/feedback_report.py --export         # data/raw/hard_cases/feedback_candidates.jsonl
    python data/scripts/feedback_report.py --recheck        # run the engine again: which reports are still wrong?

Feedback is never an allow-list. The loop is: reports -> --export -> seeds for the Haiku writers of data/scripts/hard_cases.py
(variants of each wrong decision, both labels, verified blind) -> retrain on Colab -> --recheck must show fewer wrong ones.
"""
import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from api.feedback_store import DEFAULT_PATH  # noqa: E402
from data.scripts.vietnamese_norm import detect_language  # noqa: E402

EXPORT_PATH = os.path.join(BASE_DIR, "data", "raw", "hard_cases", "feedback_candidates.jsonl")


def load(path: str = None) -> List[Dict[str, Any]]:
    path = path or os.getenv("FIREWALL_FEEDBACK_FILE") or DEFAULT_PATH
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "by_layer": dict(Counter(f"{r['kind']}:L{r.get('layer')}" for r in rows)),
        "by_language": dict(Counter(f"{r['kind']}:{detect_language(r['text'])}" for r in rows)),
    }


def to_seeds(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A reported false positive is a SAFE text (label 0); a reported miss is an ATTACK (label 1)."""
    return [{"text": r["text"], "label_binary": 0 if r["kind"] == "false_positive" else 1, "lang": detect_language(r["text"]),
             "source": "feedback", "mode": r.get("mode", "message"), "note": r.get("note", ""), "reported_decision": r.get("decision", "")}
            for r in rows]


def recheck(rows: List[Dict[str, Any]], engine=None) -> List[Dict[str, Any]]:
    """Run each reported text through the engine again (no judge). `still_wrong` is True when the decision is still the reported one."""
    if engine is None:
        from firewall.orchestrator import FirewallOrchestrator
        engine = FirewallOrchestrator()
    out = []
    for r in rows:
        if r.get("mode", "message") == "context":
            result = engine.process_context([{"id": "fb", "text": r["text"], "source": "email"}], session_id="feedback-recheck")
            decision = result["decision"]
        elif r.get("mode") in ("action", "output"):
            continue            # structured or output reports are not re-run from text alone
        else:
            decision = engine.process_input(r["text"])["decision"]
        wrong = decision != "ALLOW" if r["kind"] == "false_positive" else decision == "ALLOW"
        out.append({"id": r["id"], "kind": r["kind"], "now": decision, "still_wrong": wrong, "text": r["text"][:100]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default=None)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--recheck", action="store_true")
    args = parser.parse_args()
    rows = load(args.path)
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    if args.export:
        os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
        with open(EXPORT_PATH, "w", encoding="utf-8") as handle:
            for seed in to_seeds(rows):
                handle.write(json.dumps(seed, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows)} seeds to {EXPORT_PATH}")
    if args.recheck:
        results = recheck(rows)
        wrong = [r for r in results if r["still_wrong"]]
        print(f"re-checked {len(results)}: still wrong {len(wrong)}")
        for r in wrong[:20]:
            print(f"  {r['kind']:15s} now {r['now']:8s} {r['text']}")


if __name__ == "__main__":
    main()
