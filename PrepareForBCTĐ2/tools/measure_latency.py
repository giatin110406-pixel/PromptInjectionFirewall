"""
Latency of each stage of the engine, measured on real texts.

    python PrepareForBCTĐ2/tools/measure_latency.py --tag gpu --device cuda
    python PrepareForBCTĐ2/tools/measure_latency.py --tag cpu --device cpu

Texts: 150 short messages and 30 long documents (several windows) from dataset_v2 test, fixed sample (seed 0).
Each stage is warmed up first. Numbers are wall-clock milliseconds on THIS machine; keep the hardware note.
"""
import argparse
import json
import os
import platform
import statistics
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from firewall.orchestrator import FirewallOrchestrator  # noqa: E402

RESULTS = os.path.join(ROOT, "PrepareForBCTĐ2", "results")


def stats(values):
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(q * len(values)))]
    return {"n": len(values), "mean_ms": round(statistics.mean(values), 2), "p50_ms": round(pick(0.50), 2),
            "p95_ms": round(pick(0.95), 2), "max_ms": round(values[-1], 2)}


def timed(fn, items, warm=3):
    for item in items[:warm]:
        fn(item)
    out = []
    for item in items:
        t0 = time.perf_counter()
        fn(item)
        out.append((time.perf_counter() - t0) * 1000)
    return stats(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="default")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: cuda when available)")
    args = parser.parse_args()

    test = pd.read_csv(os.path.join(ROOT, "data", "processed", "dataset_v2_test.csv"), keep_default_na=False)
    short = test[test["text"].str.len() <= 300].sample(150, random_state=0)["text"].tolist()
    long_ = test[test["text"].str.len() >= 1200].sample(30, random_state=0)["text"].tolist()

    from firewall.classifier import MultilingualClassifier
    engine = FirewallOrchestrator(layer2=MultilingualClassifier(device=args.device))
    import torch
    info = {"machine": platform.processor() or platform.machine(), "python": platform.python_version(),
            "torch": torch.__version__, "device": getattr(engine.layer2, "device", "none"),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() and getattr(engine.layer2, "device", "") == "cuda" else None}

    report = {"info": info, "tag": args.tag}
    report["L1_signatures_short"] = timed(engine.layer1.check, short)
    report["L2_classifier_short"] = timed(engine.layer2.check, short)
    report["L2_classifier_long_docs"] = timed(engine.layer2.check, long_)
    report["pipeline_input_short"] = timed(engine.process_input, short)
    report["pipeline_input_long_docs"] = timed(engine.process_input, long_)
    chunk_sets = [[{"id": f"c{j}", "text": t, "source": "rag"} for j, t in enumerate(short[i:i + 3])] for i in range(0, 90, 3)]
    report["context_scan_3_chunks"] = timed(lambda chunks: engine.process_context(chunks, session_id="lat"), chunk_sets)
    actions = [("refund", {"user_id": "u", "order_id": "o", "amount": 50.0, "order_value": 500.0, "user_role": "finance_lead"})] * 100
    engine.actions.policy["rate_limit"]["max_sensitive_actions"] = 10 ** 6   # measure the check, not the limiter
    report["action_gate"] = timed(lambda a: engine.validate_action(a[0], a[1], session_id="lat-act"), actions)

    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, f"latency_{args.tag}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    for key, value in report.items():
        if isinstance(value, dict) and "p50_ms" in value:
            print(f"{key:28s} p50={value['p50_ms']:>8} ms  p95={value['p95_ms']:>8} ms  (n={value['n']})")
    print("info:", info)
    print("wrote", path)


if __name__ == "__main__":
    main()
