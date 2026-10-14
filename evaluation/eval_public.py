"""
Measure Layers 1, 2 and the L0-L2 pipeline on the public evaluation sets (step 4 of
docs/public_data_implementation_plan.md). Nothing here is used to train a model or to pick a threshold.

    python evaluation/eval_public.py                 # every set in data/eval/public/
    python evaluation/eval_public.py --sets deepset,dolly_instr

Per text it records:
  l1_block      Layer 1 (regex + semantic index) says BLOCK
  l2_score      highest window score of the mDeBERTa classifier; l2_flag = score >= the threshold stored with the checkpoint
  pipeline      decision of FirewallOrchestrator.process_input(use_judge=False): ALLOW / REVIEW / BLOCK / SANITIZE
Document sets (tool output, web pages, long passages) also go through process_context (Spotlighting + scan):
  ctx_decision, ctx_tainted (the session would be marked as having seen an instruction)

Rates carry 95% Wilson intervals. Rows are saved in evaluation/results/public_eval_rows/<set>.csv so a run can
resume and every number can be traced to texts. The summary is evaluation/results/public_eval.json.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_layer1 import wilson  # noqa: E402

DATA = os.path.join(BASE_DIR, "data", "eval", "public")
ROWS = os.path.join(BASE_DIR, "evaluation", "results", "public_eval_rows")
SUMMARY = os.path.join(BASE_DIR, "evaluation", "results", "public_eval.json")
DOC_SETS = {"injecagent_resp_base", "injecagent_resp_enhanced", "grayswan_ipi", "dolly_doc", "xquad_vi_doc"}
ORDER = ["deepset", "tensortrust_hijack", "tensortrust_extract", "multijail_vi", "multijail_en", "injecagent_resp_base",
         "injecagent_resp_enhanced", "grayswan_ipi", "dolly_instr", "xquad_vi_q", "injecagent_user", "dolly_doc", "xquad_vi_doc"]


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, text=True).strip()
    except Exception:
        return "unknown"


def score_set(name: str, frame: pd.DataFrame, engine, threshold: float) -> pd.DataFrame:
    path = os.path.join(ROWS, f"{name}.csv")
    if os.path.exists(path):
        cached = pd.read_csv(path, keep_default_na=False)
        if len(cached) == len(frame):
            print(f"[{name}] cached ({len(cached)} rows)")
            return cached
    records = []
    started = time.time()
    for i, row in enumerate(frame.itertuples(index=False)):
        text = str(row.text)
        r1 = engine.layer1.check(text)
        l2 = max(engine.layer2.window_scores(text))
        out = engine.process_input(text, source="user", use_judge=False)
        rec = {"i": i, "label_binary": int(row.label_binary), "lang": row.lang, "attack_type": row.attack_type,
               "chars": len(text), "l1_decision": r1["decision"], "l1_block": int(r1["decision"] == "BLOCK"),
               "l2_score": round(float(l2), 4), "l2_flag": int(l2 >= threshold), "pipeline": out["decision"],
               "stopped_at": out["stopped_at_layer"], "reason": str(out["final_reason"])[:80], "text": text[:300].replace("\n", " ")}
        if name in DOC_SETS:
            ctx = engine.process_context([{"id": "d", "text": text, "source": "tool"}], session_id=f"{name}-{i}", use_judge=False)
            rec.update(ctx_decision=ctx["decision"], ctx_tainted=int(bool(ctx["session_tainted"])))
        records.append(rec)
        if (i + 1) % 200 == 0:
            print(f"[{name}] {i + 1}/{len(frame)}  {time.time() - started:.0f}s", flush=True)
    result = pd.DataFrame(records)
    os.makedirs(ROWS, exist_ok=True)
    result.to_csv(path, index=False, encoding="utf-8")
    print(f"[{name}] done {len(result)} rows in {time.time() - started:.0f}s", flush=True)
    return result


def rate(mask: pd.Series) -> dict:
    n, k = int(len(mask)), int(mask.sum())
    return {"n": n, "hits": k, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def metrics(g: pd.DataFrame) -> dict:
    out = {"L1_block": rate(g["l1_block"] == 1), "L2_flag": rate(g["l2_flag"] == 1),
           "L1_or_L2": rate((g["l1_block"] == 1) | (g["l2_flag"] == 1)),
           "pipeline_block": rate(g["pipeline"] == "BLOCK"),
           "pipeline_block_or_review": rate(g["pipeline"].isin(["BLOCK", "REVIEW"])),
           "pipeline_allow": rate(g["pipeline"].isin(["ALLOW", "SANITIZE"]))}
    if "ctx_tainted" in g:
        out["ctx_tainted"] = rate(g["ctx_tainted"] == 1)
        out["ctx_not_allowed"] = rate(g["ctx_decision"] != "ALLOW")
    return out


def summarize(name: str, rows: pd.DataFrame) -> dict:
    entry = {"n": int(len(rows)), "by_label": {}}
    for label, g in rows.groupby("label_binary"):
        entry["by_label"][str(label)] = {"n": int(len(g)), **metrics(g)}
    entry["by_lang"] = {str(k): {"n": int(len(g)), "labels": {str(l): int(c) for l, c in g.label_binary.value_counts().items()},
                                 **{f"{lab}": metrics(g[g.label_binary == int(lab)]) for lab in g.label_binary.unique().astype(str)}}
                        for k, g in rows.groupby("lang")} if name == "deepset" else {}
    if name.startswith(("tensortrust", "injecagent_resp")):
        key = "attack_type"
        atk = rows[rows.label_binary == 1]
        entry["by_attack_type"] = {str(k): {"n": int(len(g)), "L1_or_L2": rate((g.l1_block == 1) | (g.l2_flag == 1)),
                                            "pipeline_block_or_review": rate(g.pipeline.isin(["BLOCK", "REVIEW"]))}
                                   for k, g in atk.groupby(key)}
    entry["missed_examples"] = rows[(rows.label_binary == 1) & rows.pipeline.isin(["ALLOW", "SANITIZE"])][["text", "l2_score"]].head(5).to_dict("records")
    entry["false_alarm_examples"] = rows[(rows.label_binary == 0) & rows.pipeline.isin(["BLOCK", "REVIEW"])][["text", "l2_score", "pipeline"]].head(5).to_dict("records")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", help="comma-separated set names (default: all)")
    args = parser.parse_args()
    wanted = [s.strip() for s in args.sets.split(",")] if args.sets else [n for n in ORDER if os.path.exists(os.path.join(DATA, f"{n}.csv"))]

    from firewall.orchestrator import FirewallOrchestrator

    engine = FirewallOrchestrator()
    health = engine.health()
    threshold = float(engine.layer2.threshold)
    print(f"[INFO] L2 threshold={threshold} device={getattr(engine.layer2, 'device', None)} degraded={health.get('degraded')}", flush=True)
    engine.process_input("warm up", use_judge=False)

    summary = {"git_commit": git_commit(), "l2_threshold": threshold, "l2_temperature": engine.layer2.temperature,
               "judge_used": False, "sets": {}}
    if os.path.exists(SUMMARY) and args.sets:
        previous = json.load(open(SUMMARY, encoding="utf-8"))
        summary["sets"].update(previous.get("sets", {}))
    for name in wanted:
        frame = pd.read_csv(os.path.join(DATA, f"{name}.csv"), keep_default_na=False)
        rows = score_set(name, frame, engine, threshold)
        summary["sets"][name] = summarize(name, rows)
        label = "1" if "1" in summary["sets"][name]["by_label"] else "0"
        m = summary["sets"][name]["by_label"][label]
        print(f"[{name}] label={label} n={m['n']} L1={m['L1_block']['rate']} L2={m['L2_flag']['rate']} "
              f"L1|L2={m['L1_or_L2']['rate']} pipe_block={m['pipeline_block']['rate']} pipe_block+review={m['pipeline_block_or_review']['rate']}", flush=True)
        os.makedirs(os.path.dirname(SUMMARY), exist_ok=True)
        json.dump(summary, open(SUMMARY, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {SUMMARY}")


if __name__ == "__main__":
    main()
