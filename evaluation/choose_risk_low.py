"""
Choose `exposure.risk_low` of firewall/policies.yaml (WP4) on the DEV half of data/eval/v4/friction_flows.jsonl only.

    python evaluation/choose_risk_low.py [--budget 0.02]

The rule asks for a confirmation in an exposed session even when the user typed or saved every destination, if a chunk
the session read scored `risk_low` or more on Layer 2. Its cost falls on exactly those flows: legitimate flows whose
action was cleared by provenance. For each candidate value this script counts how many dev flows it would add a
question to, and picks the LOWEST value whose added friction stays within the budget (default 2 points of the dev flows):
the lowest value asks the most often when content looks doubtful, at a bounded cost. The test half is not read.
The value never goes below FLOOR (0.30): below it, safe texts outnumber attacks in the Layer 2 score bands of the dev
data (firewall/orchestrator.py), and 18-odd cleared AI-written flows cannot place the edge lower with any confidence
(on 02/11/2026 they all scored under 0.035, so every candidate cost nothing and "lowest" would have meant 0.05).

Writes evaluation/results/risk_low_choice.json. The flows are AI-generated (data/eval/v4/README.md): the choice is a
pipeline check until the team-written set exists.
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_v4 import RES, Runner, load  # noqa: E402  (also points the review queue at a temp file)
from model_variant import arg, engine_for  # noqa: E402

CANDIDATES = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]
FLOOR = 0.30


def main():
    budget = float(arg("--budget", "0.02"))
    engine, _ = engine_for(arg("--artifacts"), arg("--bands"))
    engine.actions.risk_low = 1.0                   # off while measuring
    runner = Runner(engine)
    flows = [f for f in load("friction_flows.jsonl") if f["split"] == "dev"]
    cleared = []
    for f in flows:
        sid = runner.sid("rl")
        if any(engine.process_input(m, use_judge=False, session_id=sid)["decision"] in ("BLOCK", "REVIEW")
               for m in f["user_messages"]):
            continue
        if f.get("content"):
            runner.scan(sid, f["content"]["text"], f["content"]["source"], f"{f['id']}-c")
        out = runner.act(sid, f["action"]["type"], f["action"]["payload"], "provenance")
        if out["decision"] == "ALLOW" and out["exposed"]:
            cleared.append({"id": f["id"], "risk": engine.taint.exposure_risk(sid)})
    table = [{"risk_low": c, "added_questions": sum(r["risk"] >= c for r in cleared),
              "added_friction": round(sum(r["risk"] >= c for r in cleared) / len(flows), 4)} for c in CANDIDATES]
    within = [row for row in table if row["added_friction"] <= budget and row["risk_low"] >= FLOOR]
    chosen = min(within, key=lambda r: r["risk_low"])["risk_low"] if within else 1.0
    report = {"split": "dev", "n_flows": len(flows), "cleared_by_provenance": len(cleared), "budget": budget, "floor": FLOOR,
              "chosen": chosen, "table": table, "cleared_risks": sorted(r["risk"] for r in cleared),
              "note": "AI-generated flows: pipeline check, not a result on human-written data"}
    path = os.path.join(RES, "risk_low_choice.json")
    json.dump(report, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"dev flows={len(flows)} cleared_by_provenance={len(cleared)} chosen risk_low={chosen}")
    for row in table:
        print(f"  {row['risk_low']:.2f}: +{row['added_questions']} questions ({row['added_friction']:.1%})")
    print(f"[INFO] wrote {path}")


if __name__ == "__main__":
    main()
