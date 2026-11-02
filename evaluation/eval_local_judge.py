"""
WP8: a free judge run locally, on the same 185 borderline prompts the stand-in judge (Claude Haiku) answered.

    python evaluation/eval_local_judge.py                                  # Qwen/Qwen2.5-1.5B-Instruct
    python evaluation/eval_local_judge.py --model Qwen/Qwen3-0.6B

The prompts are evaluation/results/public_l3/manual/requests.jsonl (exact judge prompts recorded by
evaluation/eval_public_l3.py prepare; the request file holds no label). Each one is answered by the local model
(firewall/llm_provider.py LocalHFProvider, greedy), the answers go to public_l3/local_<model>/answers.jsonl (resumable),
then `eval_public_l3.score` replays them through the real judge code, exactly as for Haiku.

Writes public_l3/l3_public_eval_local_<model>.json and evaluation/results/local_judge_<model>.json (latency, parse
failures, comparison with the pipeline without judge and with the Haiku stand-in). Decision rule of the plan: switch
the judge on by default only if false blocks drop and recall does not.
"""
import json
import os
import shutil
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))

import eval_public_l3 as l3  # noqa: E402
from model_variant import arg  # noqa: E402


def totals(report):
    """Attacks blocked and safe texts blocked over all sets, without and with the judge."""
    out = {"attacks": 0, "safe": 0, "attacks_blocked_without": 0, "attacks_blocked_with": 0, "safe_blocked_without": 0,
           "safe_blocked_with": 0, "attacks_review_with": 0, "safe_review_with": 0}
    for entry in report["per_set"].values():
        for label in ("attacks", "safe"):
            g = entry.get(label)
            if not g:
                continue
            out[label] += g["n"]
            out[f"{label}_blocked_without"] += g["blocked_without_judge"]["hits"]
            out[f"{label}_blocked_with"] += g["blocked_with_judge"]["hits"]
            out[f"{label}_review_with"] += g["held_for_review_with_judge"]
    return out


def main():
    from firewall.judge import parse_verdict
    from firewall.llm_provider import LocalHFProvider

    model = arg("--model", "Qwen/Qwen2.5-1.5B-Instruct")
    slug = model.split("/")[-1].lower().replace(".", "_")
    out_dir = os.path.join(l3.OUT, f"local_{slug}")
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy(os.path.join(l3.MANUAL, "requests.jsonl"), os.path.join(out_dir, "requests.jsonl"))
    answers_path = os.path.join(out_dir, "answers.jsonl")
    done = {}
    if os.path.exists(answers_path):
        done = {json.loads(line)["id"]: json.loads(line) for line in open(answers_path, encoding="utf-8") if line.strip()}
    requests = [json.loads(line) for line in open(os.path.join(out_dir, "requests.jsonl"), encoding="utf-8") if line.strip()]
    provider = LocalHFProvider(model=model)
    latencies, unparsed = [], 0
    with open(answers_path, "a", encoding="utf-8") as handle:
        for n, req in enumerate(requests, 1):
            if req["id"] in done:
                latencies.append(done[req["id"]].get("ms", 0))
                continue
            started = time.perf_counter()
            text = provider.complete(req["prompt"], system=req.get("system"), max_tokens=200, temperature=0.0)
            ms = round((time.perf_counter() - started) * 1000)
            latencies.append(ms)
            handle.write(json.dumps({"id": req["id"], "text": text, "ms": ms}, ensure_ascii=False) + "\n")
            handle.flush()
            if n % 20 == 0:
                print(f"{n}/{len(requests)} answered, last {ms} ms", flush=True)
    for line in open(answers_path, encoding="utf-8"):
        if line.strip():
            try:
                parse_verdict(json.loads(line)["text"])
            except Exception:
                unparsed += 1
    local = l3.score(out_dir, f"l3_public_eval_local_{slug}.json", judge_name=f"{model} (local, transformers, greedy)")
    haiku = json.load(open(os.path.join(l3.OUT, "l3_public_eval.json"), encoding="utf-8"))
    t_local, t_haiku = totals(local), totals(haiku)
    warm = latencies[1:] or latencies
    summary = {
        "model": model, "prompts": len(requests), "unparsed_replies": unparsed,
        "latency_ms": {"p50": statistics.median(warm), "p95": sorted(warm)[int(0.95 * (len(warm) - 1))], "first_call": latencies[0]},
        "judge_timeout_ms": 8000,
        "local": t_local, "haiku_stand_in": t_haiku,
        "verdicts_by_side": {"local": local.get("judge_verdicts_by_side"), "haiku": haiku.get("judge_verdicts_by_side")},
        "false_blocks_drop": t_local["safe_blocked_with"] < t_local["safe_blocked_without"],
        "recall_kept": t_local["attacks_blocked_with"] + t_local["attacks_review_with"] >= t_local["attacks_blocked_without"],
        "note": "185 prompts recorded with the v3 engine bands (0.30-0.98); same prompts for both judges",
    }
    summary["switch_on_by_default"] = bool(summary["false_blocks_drop"] and summary["recall_kept"]
                                            and summary["latency_ms"]["p95"] < summary["judge_timeout_ms"])
    path = os.path.join(ROOT, "evaluation", "results", f"local_judge_{slug}.json")
    json.dump(summary, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in summary.items() if k != "verdicts_by_side"}, indent=1, ensure_ascii=False))
    print(f"[INFO] wrote {path}")


if __name__ == "__main__":
    main()
