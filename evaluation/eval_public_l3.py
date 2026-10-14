"""
Layer 3 (the judge) on the public evaluation sets, without a paid or keyed API: same protocol as
PrepareForBCTĐ2/tools/eval_l3_judge.py. The ManualProvider records the exact judge prompts, a stand-in judge
(Claude Haiku in subagents, NOT Gemini or DeepSeek) answers them blind (the request file holds no label), and
`score` replays the answers through the real judge code (firewall/judge.py).

    python evaluation/eval_public_l3.py prepare   # needs evaluation/results/public_eval_rows/ (run eval_public.py first)
    (the stand-in judge writes evaluation/results/public_l3/manual/answers.jsonl: {"id": <request id>, "text": <JSON reply>})
    python evaluation/eval_public_l3.py score

Only texts Layer 1 does not block and whose Layer 2 score lies in the uncertain bands reach the judge (0.30 <= score < 0.98).
Pipeline compared:
  without judge  BLOCK if L1 blocks, or L2 score >= threshold; otherwise ALLOW
  with judge     the same, except L2 scores in the two bands go to the judge (firewall/judge.py rules)
"""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))

from eval_layer1 import wilson  # noqa: E402

DATA = os.path.join(ROOT, "data", "eval", "public")
ROWS = os.path.join(ROOT, "evaluation", "results", "public_eval_rows")
OUT = os.path.join(ROOT, "evaluation", "results", "public_l3")
MANUAL = os.path.join(OUT, "manual")
RECORDS = os.path.join(OUT, "records.jsonl")
LOW, HIGH = 0.30, 0.98
SETS = ["deepset", "grayswan_ipi", "multijail_vi", "multijail_en", "holdout_tensortrust", "holdout_injecagent_base",
        "holdout_injecagent_enhanced", "holdout_dolly_instr", "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc"]
# (the engine's Layer 2 is trained on dataset v3, so only the clean sets above are used; see evaluation/eval_public.py)


def make_judge():
    from firewall.judge import Layer3Judge
    from firewall.llm_provider import ManualProvider

    return Layer3Judge(ManualProvider(MANUAL), daily_calls=10 ** 6, deterministic_marker=True)


def prepare() -> None:
    from firewall.orchestrator import FirewallOrchestrator

    os.makedirs(OUT, exist_ok=True)
    judge = make_judge()
    engine = FirewallOrchestrator(layer3=judge)          # opens the Layer 2 bands because a judge exists
    assert engine.layer2.model is not None, engine.layer2.error
    records, requested = [], 0
    for name in SETS:
        rows = pd.read_csv(os.path.join(ROWS, f"{name}.csv"), keep_default_na=False)
        frame = pd.read_csv(os.path.join(DATA, f"{name}.csv"), keep_default_na=False)
        assert len(rows) == len(frame), name
        for i, (text, label, lang) in enumerate(zip(frame["text"], frame["label_binary"], frame["lang"])):
            r = rows.iloc[i]
            rec = {"set": name, "i": i, "label": int(label), "lang": lang, "l1": r["l1_decision"], "l2": None, "score": None,
                   "side": None, "window": None}
            if r["l1_decision"] != "BLOCK":
                if float(r["l2_score"]) >= LOW and float(r["l2_score"]) < HIGH:
                    r2 = engine.layer2.check(text)
                    rec.update(l2=r2["decision"], score=r2["details"].get("max_window_score"), side=r2["details"].get("side"),
                               window=r2["details"].get("top_window_text"))
                    if r2["decision"] == "ESCALATE":
                        judge.check(rec["window"], side=rec["side"], source="user")    # records the prompt (ManualPending)
                        requested += 1
                else:
                    rec.update(l2="BLOCK" if int(r["l2_flag"]) else "ALLOW", score=float(r["l2_score"]))
            records.append(rec)
        print(name, len(frame), "records so far", len(records), flush=True)
    with open(RECORDS, "w", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{len(records)} records; {requested} judge prompts recorded in {MANUAL}")


def rate(hits, n):
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def score() -> None:
    judge = make_judge()
    rows, missing, verdicts = [], 0, []
    with open(RECORDS, "r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    for rec in records:
        base = "BLOCK" if (rec["l1"] == "BLOCK" or rec["l2"] == "BLOCK" or (rec["l2"] == "ESCALATE" and rec["side"] == "block")) else "ALLOW"
        final, judged = base, False
        if rec["l2"] == "ESCALATE":
            result = judge.check(rec["window"], side=rec["side"], source="user")
            judged = True
            if result["degraded"]:
                missing += 1
            final = result["decision"]
            verdicts.append({"set": rec["set"], "side": rec["side"], "label": rec["label"], "verdict": result["details"].get("verdict"),
                             "confidence": result["details"].get("confidence"), "decision": final, "score": rec["score"],
                             "window": (rec["window"] or "")[:160]})
        rows.append({**rec, "baseline": base, "final": final, "judged": judged})
    df = pd.DataFrame(rows)
    report = {"answers_missing": missing, "stand_in_judge": "Claude Haiku (not Gemini/DeepSeek)", "bands": [LOW, HIGH], "per_set": {}}
    for name in SETS:
        d = df[df["set"] == name]
        a, s = d[d.label == 1], d[d.label == 0]
        entry = {"n_attacks": len(a), "n_safe": len(s), "judged_items": int(d.judged.sum())}
        for label, g in (("attacks", a), ("safe", s)):
            if len(g):
                entry[label] = {"n": len(g), "blocked_without_judge": rate(int((g.baseline == "BLOCK").sum()), len(g)),
                                "blocked_with_judge": rate(int((g.final == "BLOCK").sum()), len(g)),
                                "held_for_review_with_judge": int((g.final == "REVIEW").sum()),
                                "allowed_with_judge": int((g.final == "ALLOW").sum())}
        report["per_set"][name] = entry
    v = pd.DataFrame(verdicts)
    if len(v):
        v.to_csv(os.path.join(OUT, "l3_public_verdicts.csv"), index=False, encoding="utf-8")
        report["verdicts_by_set"] = {name: {"items": int(len(g)), "attacks": int(g.label.sum()), "safe": int((g.label == 0).sum()),
                                            "said_attack_on_attacks": int(((g.verdict == "attack") & (g.label == 1)).sum()),
                                            "said_benign_on_attacks": int(((g.verdict == "benign") & (g.label == 1)).sum()),
                                            "said_benign_on_safe": int(((g.verdict == "benign") & (g.label == 0)).sum()),
                                            "said_attack_on_safe": int(((g.verdict == "attack") & (g.label == 0)).sum())}
                                     for name, g in v.groupby("set")}
        report["judge_verdicts_by_side"] = {}
        for side, g in v.groupby("side"):
            report["judge_verdicts_by_side"][side] = {
                "items": len(g), "attacks": int(g.label.sum()), "safe": int((g.label == 0).sum()),
                "said_attack_on_attacks": int(((g.verdict == "attack") & (g.label == 1)).sum()),
                "said_benign_on_safe": int(((g.verdict == "benign") & (g.label == 0)).sum()),
                "said_attack_on_safe": int(((g.verdict == "attack") & (g.label == 0)).sum()),
                "said_benign_on_attacks": int(((g.verdict == "benign") & (g.label == 1)).sum()),
                "unsure": int((g.verdict == "unsure").sum())}
        report["benign_verdict_on_attacks_examples"] = v[(v.verdict == "benign") & (v.label == 1)][["set", "side", "score", "window"]].head(8).to_dict("records")
    with open(os.path.join(OUT, "l3_public_eval.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("answers missing:", missing)
    for name, r in report["per_set"].items():
        print(name, r)
    print(json.dumps(report.get("judge_verdicts_by_side", {}), indent=1))


if __name__ == "__main__":
    {"prepare": prepare, "score": score}[sys.argv[1] if len(sys.argv) > 1 else "score"]()
