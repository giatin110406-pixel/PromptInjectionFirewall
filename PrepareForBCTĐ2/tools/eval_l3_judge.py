"""
Measure Layer 3 (the judge) without a paid or keyed API: the ManualProvider records the exact judge prompts, a stand-in
judge (Claude Haiku in subagents, NOT Gemini) answers them, and `score` replays the answers through the real judge code.

    python PrepareForBCTĐ2/tools/eval_l3_judge.py prepare   # run L1+L2 on the evaluation sets, record the judge prompts
    (the stand-in judge writes results/l3/manual/answers.jsonl: {"id": <request id>, "text": <JSON reply>})
    python PrepareForBCTĐ2/tools/eval_l3_judge.py score     # decisions with and without the judge, per set (answers from the stand-in judge)
    python PrepareForBCTĐ2/tools/eval_l3_judge.py live      # the same with the real provider (Gemini, key in .env); ~64 calls, paced

Sets: dataset_v2 validation/test, external dev/test halves, vi_test_v1 dev/test halves. The Layer 2 bands were chosen on
validation + the dev halves; report the test sets.

Pipeline compared:
  without judge  BLOCK if L1 blocks, or L2 score >= threshold; otherwise ALLOW
  with judge     the same, except L2 scores in the two uncertain bands go to the judge (firewall/judge.py rules)
"""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))

from eval_layer1 import load_set, wilson  # noqa: E402

OUT = os.path.join(ROOT, "PrepareForBCTĐ2", "results", "l3")
RECORDS = os.path.join(OUT, "records.jsonl")
MANUAL = os.path.join(OUT, "manual")
SETS = ["validation", "external_dev", "vi_dev", "test", "external_test", "vi_test"]


def make_judge(with_answers: bool, live: bool = False):
    from firewall.judge import Layer3Judge
    from firewall.llm_provider import GeminiProvider, ManualProvider, load_env_file

    if live:
        load_env_file()
        provider = GeminiProvider(timeout=30.0, retries=2)
        return Layer3Judge(PacedProvider(provider, 4.0), daily_calls=10 ** 6, deterministic_marker=True)
    return Layer3Judge(ManualProvider(MANUAL), daily_calls=10 ** 6, deterministic_marker=True)


class PacedProvider:
    """Waits between calls so a free-tier key stays under its per-minute limit."""

    def __init__(self, inner, seconds):
        import time
        self.inner, self.seconds, self.name, self._last, self._time = inner, seconds, inner.name, 0.0, time

    def complete(self, *args, **kwargs):
        wait = self._last + self.seconds - self._time.time()
        if wait > 0:
            self._time.sleep(wait)
        try:
            return self.inner.complete(*args, **kwargs)
        finally:
            self._last = self._time.time()


def prepare() -> None:
    from firewall.orchestrator import FirewallOrchestrator

    os.makedirs(OUT, exist_ok=True)
    judge = make_judge(False)
    engine = FirewallOrchestrator(layer3=judge)          # opens the Layer 2 bands because a judge exists
    assert engine.layer2.model is not None, engine.layer2.error
    records, requested = [], 0
    for name in SETS:
        frame = load_set(name)
        for text, label, lang in zip(frame["text"], frame["label_binary"], frame["lang"]):
            r1 = engine.layer1.check(text)
            rec = {"set": name, "label": int(label), "lang": lang, "l1": r1["decision"], "l2": None, "score": None,
                   "side": None, "window": None}
            if r1["decision"] != "BLOCK":
                r2 = engine.layer2.check(text)
                rec.update(l2=r2["decision"], score=r2["details"].get("max_window_score"), side=r2["details"].get("side"),
                           window=r2["details"].get("top_window_text"))
                if r2["decision"] == "ESCALATE":
                    judge.check(rec["window"], side=rec["side"], source="user")    # records the prompt (ManualPending)
                    requested += 1
            records.append(rec)
        print(name, len(frame), "records so far", len(records))
    with open(RECORDS, "w", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"{len(records)} records; {requested} judge prompts recorded in {MANUAL}")


def rate(hits, n):
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def score(live: bool = False) -> None:
    judge = make_judge(True, live=live)
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
                             "confidence": result["details"].get("confidence"), "decision": final, "score": rec["score"]})
        rows.append({**rec, "baseline": base, "final": final, "judged": judged})
    df = pd.DataFrame(rows)
    report = {"answers_missing": missing, "per_set": {}}
    for name in SETS:
        d = df[df["set"] == name]
        a, s = d[d.label == 1], d[d.label == 0]
        report["per_set"][name] = {
            "n_attacks": len(a), "n_safe": len(s), "judged_items": int(d.judged.sum()),
            "without_judge": {"attacks_blocked": rate(int((a.baseline == "BLOCK").sum()), len(a)),
                              "safe_blocked": rate(int((s.baseline == "BLOCK").sum()), len(s))},
            "with_judge": {"attacks_blocked": rate(int((a.final == "BLOCK").sum()), len(a)),
                           "attacks_held_for_review": int((a.final == "REVIEW").sum()),
                           "attacks_allowed": int((a.final == "ALLOW").sum()),
                           "safe_blocked": rate(int((s.final == "BLOCK").sum()), len(s)),
                           "safe_held_for_review": int((s.final == "REVIEW").sum()),
                           "safe_allowed": int((s.final == "ALLOW").sum())}}
    v = pd.DataFrame(verdicts)
    if len(v):
        report["judge_verdicts_by_side"] = {}
        for side, g in v.groupby("side"):
            report["judge_verdicts_by_side"][side] = {
                "items": len(g), "attacks": int(g.label.sum()), "safe": int((g.label == 0).sum()),
                "said_attack_on_attacks": int(((g.verdict == "attack") & (g.label == 1)).sum()),
                "said_benign_on_safe": int(((g.verdict == "benign") & (g.label == 0)).sum()),
                "said_attack_on_safe": int(((g.verdict == "attack") & (g.label == 0)).sum()),
                "said_benign_on_attacks": int(((g.verdict == "benign") & (g.label == 1)).sum()),
                "unsure": int((g.verdict == "unsure").sum())}
    with open(os.path.join(OUT, "l3_eval_gemini.json" if live else "l3_eval.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("answers missing:", missing)
    for name, r in report["per_set"].items():
        w, b = r["with_judge"], r["without_judge"]
        print(f"{name:14s} judged {r['judged_items']:>3} | attacks blocked {b['attacks_blocked']['hits']}/{r['n_attacks']} -> {w['attacks_blocked']['hits']} "
              f"(+{w['attacks_held_for_review']} held, {w['attacks_allowed']} allowed) | safe blocked {b['safe_blocked']['hits']}/{r['n_safe']} -> "
              f"{w['safe_blocked']['hits']} (+{w['safe_held_for_review']} held)")
    print(json.dumps(report.get("judge_verdicts_by_side", {}), indent=1))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "score"
    {"prepare": prepare, "score": score, "live": lambda: score(live=True)}[mode]()
