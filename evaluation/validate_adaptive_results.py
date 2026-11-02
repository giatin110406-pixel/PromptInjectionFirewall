"""Independently audit H6 rates against the per-query checkpoint, without models."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="v3b")
    parser.add_argument("--baseline-hash", help="SHA-256 of canonical base report excluding adaptive, recorded BEFORE the run")
    parser.add_argument("--policy-snapshot", help="policy snapshot whose exact SHA-256 must match the measured run")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]*", args.tag):
        parser.error("invalid tag")
    suffix = "_" + args.tag if args.tag else ""
    result_path = ROOT / f"evaluation/results/v4_eval{suffix}.json"
    report = json.loads(result_path.read_text(encoding="utf-8"))
    result = report["adaptive"]
    checkpoint = json.loads((ROOT / f"evaluation/results/v4_adaptive{suffix}_checkpoint.json").read_text(encoding="utf-8"))
    rows, budgets = checkpoint["rows"], result["budgets"]
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(checkpoint["provenance"] == result["provenance"], "checkpoint/report provenance differs")
    require(len(rows) == result["n"] and len({r["id"] for r in rows}) == len(rows), "scenario count/IDs")
    source = ROOT / "data/eval/v4/attack_scenarios_vi.jsonl"
    scenarios = [json.loads(l) for l in source.read_text(encoding="utf-8").splitlines() if l.strip()]
    scenarios = [s for s in scenarios if s["has_explicit_instruction"] is True]
    require([s["id"] for s in scenarios] == [r["id"] for r in rows], "not the complete explicit input")
    baseline = {r["id"]: r for r in report["attack_rows"]}
    for scenario, row in zip(scenarios, rows):
        history = row["history"]
        require(row["control"] == baseline[row["id"]]["control"], "control differs from base report")
        require(row["executable"] == (row["control"] == "ALLOW"), "executable mismatch")
        require(len(history) == row["trials"] <= budgets[-1], "query count exceeds budget")
        require(history[0]["text_sha256"] == hashlib.sha256(scenario["content"].encode("utf-8")).hexdigest(), "original not trial 1")
        seen = {}
        for trial, event in enumerate(history, 1):
            require(event["trial"] == trial and event["text_sha256"] not in seen, "duplicate query or trial gap")
            require(0 <= event["l2_score"] <= 1, "invalid score")
            require(0 <= event["depth"] <= result["provenance"]["max_depth"], "depth limit")
            if trial == 1:
                require(event["parent_sha256"] is None and event["depth"] == 0, "invalid root")
            else:
                require(event["parent_sha256"] in seen, "parent was not queried before child")
                require(event["depth"] == seen[event["parent_sha256"]] + 1, "parent/child depth")
            seen[event["text_sha256"]] = event["depth"]
        for budget in budgets:
            prefix, saved = history[:budget], row["checkpoints"][str(budget)]
            require(saved["queries"] == len(prefix), "milestone query count")
            require(saved["detector_bypass"] == any(not h["flagged"] for h in prefix), "detector hit mismatch")
            for mode in ("detection", "provenance"):
                require(saved["asr_action"][mode] == any(h["decisions"][mode] == "ALLOW" for h in prefix), "action hit mismatch")
            require(saved["best_l2_score"] == min(h["l2_score"] for h in prefix), "best score mismatch")
    eligible = [r for r in rows if r["executable"]]
    def rate(hits, n):
        return round(hits / n, 6) if n else None
    for budget in budgets:
        key = str(budget)
        require(result["detector_bypass_at"][key] == rate(sum(r["checkpoints"][key]["detector_bypass"] for r in rows), len(rows)), "aggregate detector rate")
        for mode in ("detection", "provenance"):
            require(result["asr_action_at"][mode][key] == rate(sum(r["checkpoints"][key]["asr_action"][mode] for r in eligible), len(eligible)), "aggregate action rate")
    require(result["executable"] == len(eligible), "ASR denominator")
    require(result["total_queries"] == sum(r["trials"] for r in rows), "total queries")
    policy_path = Path(args.policy_snapshot).resolve() if args.policy_snapshot else ROOT / "firewall/policies.yaml"
    paths = {"input_sha256": source, "transforms_sha256": ROOT / "evaluation/adaptive_transforms.py",
             "search_sha256": ROOT / "evaluation/eval_v4_adaptive.py", "policy_sha256": policy_path}
    for key, path in paths.items():
        require(result["provenance"][key] == hashlib.sha256(path.read_bytes()).hexdigest(), "stale source: " + str(path))
    without_adaptive = {k: v for k, v in report.items() if k != "adaptive"}
    base_hash = hashlib.sha256(json.dumps(without_adaptive, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if args.baseline_hash:
        require(base_hash == args.baseline_hash, "base report fields changed")
    image_path = ROOT / f"evaluation/results/v4_adaptive{suffix}.png"
    require(image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and image_path.stat().st_size > 1000, "missing PNG")
    # All executable actions except the policy's write class; describe the
    # chosen scope explicitly instead of interpreting a voucher as a transfer.
    import yaml
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    sensitive = [r for r in eligible if policy["actions"][r["action"]]["class"] in {"money", "identity", "privilege", "data"}]
    audit = dict(passed=True, n=len(rows), executable=len(eligible), total_queries=result["total_queries"], budgets=budgets,
                 duplicate_queries=0, all_milestones_recomputed_from_history=True, sources_match_provenance=True,
                 policy_snapshot=str(policy_path.relative_to(ROOT)) if policy_path.is_relative_to(ROOT) else str(policy_path),
                 current_policy_matches_run=hashlib.sha256((ROOT / "firewall/policies.yaml").read_bytes()).hexdigest() == result["provenance"]["policy_sha256"],
                 base_fields_unchanged=base_hash == args.baseline_hash if args.baseline_hash else None,
                 base_without_adaptive_sha256=base_hash,
                 sensitive_subset=dict(n=len(sensitive), scope="clean control ALLOW; policy class money, identity, privilege or data",
                                       asr_action_at={m: {str(b): rate(sum(r["checkpoints"][str(b)]["asr_action"][m] for r in sensitive), len(sensitive)) for b in budgets} for m in ("detection", "provenance")}),
                 image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest())
    target = ROOT / f"evaluation/results/handoff/h6_validation{suffix}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
