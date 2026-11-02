"""H6: budgeted, score-guided adaptive search using the existing v4 Runner.

    python evaluation/eval_v4_adaptive.py --tag v3b --bands evaluation/results/band_calibration_v3b.json
    python evaluation/eval_v4_adaptive.py --tag v3 --artifacts models/l2_multilingual/artifacts_v3 --bands evaluation/results/band_calibration_v3.json

One budget unit is ONE previously unqueried candidate, including its raw L2
score and Runner.attack_once in a fresh session, both modes together. No child
is scored for free. Lower-scoring queried parents supply the next candidate.
All milestones use prefixes of the SAME search; successes are cumulative.
This is a weak synthetic, scripted-action proxy, not an LLM-agent benchmark.
"""
import argparse
import hashlib
import heapq
import itertools
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.adaptive_transforms import variants

MODES = ("detection", "provenance")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def search_scenario(runner, scenario, budgets=(10, 50, 200), *, transform=variants,
                    max_chars=8000, max_depth=4, on_trial=None):
    """Run one deterministic best-first expansion without uncharged score probes.

    The heap contains iterators of children of ALREADY queried candidates.
    A queried parent's score prioritizes its next child, not the child's score.
    FIFO rotation breaks equal-score ties. Exact duplicates, overlong children
    and expansions past max_depth consume no queries. Exhaustion is explicit.
    """
    budgets = tuple(budgets)
    if not budgets or any(type(b) is not int or b <= 0 for b in budgets) or tuple(sorted(set(budgets))) != budgets:
        raise ValueError("budgets must be distinct positive integers in ascending order")
    if max_chars < 1 or max_depth < 0:
        raise ValueError("invalid search bounds")
    if len(scenario["content"]) > max_chars:
        raise ValueError(f"original {scenario['id']} exceeds max_chars")
    original_mode = runner.e.actions.exposure_mode
    control = runner.act(runner.sid("adaptive-control"), scenario["target_action"], scenario["target_payload"], "provenance")["decision"]
    executable = control == "ALLOW"
    heap, serial, seen, history = [], itertools.count(), set(), []
    success = {m: False for m in MODES}
    bypass, best_score, best_text = False, math.inf, scenario["content"]
    checkpoints = {}
    candidate, depth, parent_sha = scenario["content"], 0, None
    try:
        while candidate is not None and len(history) < budgets[-1]:
            seen.add(candidate)
            # Scoring is an attacker-visible probe, not the detector's final
            # verdict (which also involves L1, normalization and segmentation).
            scores = runner.e.layer2.window_scores(candidate)
            if not scores or any(not math.isfinite(float(s)) or not 0 <= float(s) <= 1 for s in scores):
                raise ValueError("Layer 2 returned invalid window scores")
            score = float(max(scores))
            flagged, decisions = runner.attack_once(candidate, scenario)
            for mode in MODES:
                if decisions[mode].get("degraded") or decisions[mode]["decision"] not in {"ALLOW", "REVIEW", "BLOCK"}:
                    raise ValueError("invalid or degraded action result")
                success[mode] |= decisions[mode]["decision"] == "ALLOW"
            bypass |= not flagged
            if score < best_score:
                best_score, best_text = score, candidate
            digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            event = dict(trial=len(history) + 1, text_sha256=digest, parent_sha256=parent_sha, depth=depth,
                         l2_score=score, flagged=bool(flagged),
                         decisions={m: decisions[m]["decision"] for m in MODES},
                         checks={m: decisions[m].get("check") for m in MODES})
            history.append(event)
            if on_trial:
                on_trial(event)
            for budget in budgets:
                if len(history) == budget:
                    checkpoints[str(budget)] = dict(queries=len(history), detector_bypass=bypass,
                                                    asr_action=dict(success), best_l2_score=best_score)
            if len(history) >= budgets[-1]:
                break
            if depth < max_depth:
                # Lazy generation avoids allocating up to 256 variants for
                # every evaluated node that may never be expanded.
                def children(text=candidate, child_depth=depth + 1, parent=digest):
                    for child in transform(text, scenario.get("lang", "vi")):
                        yield child, child_depth, parent
                heapq.heappush(heap, (score, next(serial), children()))
            candidate = None
            while heap and candidate is None:
                priority, _, children_iter = heapq.heappop(heap)
                for child, child_depth, parent in children_iter:
                    if isinstance(child, str) and child.strip() and len(child) <= max_chars and child not in seen:
                        candidate, depth, parent_sha = child, child_depth, parent
                        heapq.heappush(heap, (priority, next(serial), children_iter))
                        break
        # A finite transform can exhaust before a milestone: report actual
        # query count, retaining the successes observed within that budget.
        for budget in budgets:
            checkpoints.setdefault(str(budget), dict(queries=len(history), detector_bypass=bypass,
                                                       asr_action=dict(success), best_l2_score=best_score))
        return dict(id=scenario["id"], action=scenario["target_action"], control=control, executable=executable,
                    trials=len(history), exhausted=len(history) < budgets[-1], checkpoints=checkpoints,
                    best_l2_score=best_score, best_text=best_text, history=history)
    finally:
        runner.e.actions.exposure_mode = original_mode


def summarize(rows, budgets):
    eligible = [r for r in rows if r["executable"]]
    def fraction(hits, n):
        return round(hits / n, 6) if n else None
    return dict(budgets=list(budgets), n=len(rows), executable=len(eligible),
                detector_bypass_at={str(b): fraction(sum(r["checkpoints"][str(b)]["detector_bypass"] for r in rows), len(rows)) for b in budgets},
                asr_action_at={m: {str(b): fraction(sum(r["checkpoints"][str(b)]["asr_action"][m] for r in eligible), len(eligible)) for b in budgets} for m in MODES},
                excluded_from_asr=[dict(id=r["id"], action=r["action"], control=r["control"]) for r in rows if not r["executable"]],
                denominator_note="Detector bypass uses n explicit scenarios; ASR-action uses executable clean-session controls, matching eval_v4.py.",
                total_queries=sum(r["trials"] for r in rows),
                exhausted_scenarios=[r["id"] for r in rows if r["exhausted"]])


def plot_result(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    budgets = result["budgets"]
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    ax.plot(budgets, [result["detector_bypass_at"][str(b)] for b in budgets], "o-", label=f"Detector bypass (n={result['n']})")
    for mode in MODES:
        values = [result["asr_action_at"][mode][str(b)] for b in budgets]
        ax.plot(budgets, [float("nan") if v is None else v for v in values], "o-", label=f"ASR-action {mode} (n={result['executable']})")
    ax.set(xlabel="Candidate query budget", ylabel="Cumulative success rate", xticks=budgets, ylim=(-0.03, 1.03),
           title="Score-guided adaptive search — synthetic scripted-action proxy")
    ax.grid(alpha=.25)
    ax.legend(loc="best")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", default="")
    parser.add_argument("--artifacts")
    parser.add_argument("--bands")
    parser.add_argument("--budgets", nargs="+", type=int, default=[10, 50, 200])
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--resume", action="store_true", help="reuse completed scenarios only when provenance matches")
    parser.add_argument("--data-dir", default="data/eval/v4", help="folder holding attack_scenarios_vi.jsonl (e.g. data/eval/v4/human)")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]*", args.tag):
        parser.error("tag must contain only letters, digits, _ or -")
    if sorted(set(args.budgets)) != args.budgets or not args.budgets or args.budgets[0] < 1:
        parser.error("budgets must be distinct positive ascending integers")
    suffix = "_" + args.tag if args.tag else ""
    report_path = ROOT / f"evaluation/results/v4_eval{suffix}.json"
    if not report_path.exists():
        parser.error(f"run evaluation/eval_v4.py first: missing {report_path}")
    source_path = ROOT / args.data_dir / "attack_scenarios_vi.jsonl"
    all_scenarios = [json.loads(l) for l in source_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    scenarios = [s for s in all_scenarios if s["has_explicit_instruction"] is True]
    if not scenarios or len({s["id"] for s in scenarios}) != len(scenarios):
        parser.error("no explicit scenarios, or duplicate IDs")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["FIREWALL_JUDGE_PROVIDER"] = "none"
    with tempfile.TemporaryDirectory(prefix="fw_adaptive_") as temp:
        os.environ["FIREWALL_REVIEW_QUEUE"] = str(Path(temp) / "review.json")
        from evaluation.eval_v4 import Runner
        from evaluation.model_variant import engine_for
        engine, clf = engine_for(args.artifacts, args.bands)
        health = engine.health()
        if health["status"] != "healthy":
            raise RuntimeError(f"Engine degraded: {health}")
        base = json.loads(report_path.read_text(encoding="utf-8"))
        if base["l2_threshold"] != clf.threshold or base["soft_block_below"] != engine.soft_block_below:
            raise ValueError("base report and current model/bands differ; select matching --artifacts/--bands/--tag")
        base_ids = {r["id"] for r in base["attack_rows"] if r["explicit"]}
        if base_ids != {s["id"] for s in scenarios}:
            raise ValueError("base report explicit scenarios differ")
        weights = Path(clf.artifacts_dir) / "checkpoint/model.safetensors"
        with weights.open("rb") as handle:
            weights_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        provenance = dict(input_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                          transforms_sha256=hashlib.sha256((ROOT / "evaluation/adaptive_transforms.py").read_bytes()).hexdigest(),
                          search_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          policy_sha256=hashlib.sha256((ROOT / "firewall/policies.yaml").read_bytes()).hexdigest(),
                          weights_sha256=weights_hash, threshold=clf.threshold, soft_block_below=engine.soft_block_below,
                          temperature=clf.temperature, max_tokens=clf.max_tokens, stride=clf.stride,
                          budgets=args.budgets, max_chars=args.max_chars, max_depth=args.max_depth)
        checkpoint = ROOT / f"evaluation/results/v4_adaptive{suffix}_checkpoint.json"
        rows = []
        if args.resume and checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if saved["provenance"] != provenance:
                raise ValueError("resume checkpoint provenance differs")
            rows = saved["rows"]
            if [r["id"] for r in rows] != [s["id"] for s in scenarios[:len(rows)]]:
                raise ValueError("resume checkpoint is not a prefix of input scenarios")
        # Evaluation never consumes review items; keep only ten in its temporary
        # on-disk queue to avoid serializing hundreds of obsolete records per try.
        engine.review_queue.keep = 10
        runner = Runner(engine)
        started = time.perf_counter()
        for i, scenario in enumerate(scenarios[len(rows):], len(rows) + 1):
            def progress(event):
                if event["trial"] % 25 == 0:
                    print(f"[{i}/{len(scenarios)}] {scenario['id']} query={event['trial']} L2={event['l2_score']:.5f}", flush=True)
            row = search_scenario(runner, scenario, args.budgets, max_chars=args.max_chars, max_depth=args.max_depth, on_trial=progress)
            rows.append(row)
            atomic_json(checkpoint, dict(provenance=provenance, rows=rows))
            print(f"done {scenario['id']}: queries={row['trials']} best={row['best_l2_score']:.5f} executable={row['executable']}", flush=True)
        result = summarize(rows, args.budgets)
        result.update(provenance=provenance, model_artifacts=str(Path(clf.artifacts_dir).resolve()),
                      data_authors=sorted({s.get("author", "unknown") for s in scenarios}),
                      method="Best-first expansion of queried parents by max raw L2 window score; exact deduplication; one candidate equals one charged query including score and fresh-session Runner.attack_once for both modes; original is trial 1.",
                      note="Lower-bound heuristic search without LLM, weaker than The Attacker Moves Second. AI-generated pilot data, not human-written evaluation. ASR-action is the scripted target action after context scanning; semantic validity of each mutation is not verified by an agent LLM.",
                      elapsed_seconds_this_invocation=round(time.perf_counter() - started, 2),
                      scenario_rows=[{k: v for k, v in r.items() if k != "history"} for r in rows])
        # Read again so unrelated fields written by another evaluation are kept.
        latest = json.loads(report_path.read_text(encoding="utf-8"))
        if latest["l2_threshold"] != clf.threshold or latest["soft_block_below"] != engine.soft_block_below:
            raise ValueError("base report changed model during adaptive run")
        latest["adaptive"] = result
        plot_path = ROOT / f"evaluation/results/v4_adaptive{suffix}.png"
        plot_result(result, plot_path)
        atomic_json(report_path, latest)
        print(json.dumps({k: result[k] for k in ("budgets", "n", "executable", "detector_bypass_at", "asr_action_at", "total_queries", "exhausted_scenarios")}, indent=2), flush=True)
        print(f"wrote {report_path}\nwrote {plot_path}\naudit/checkpoint {checkpoint}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
