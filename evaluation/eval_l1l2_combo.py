"""
Which Layer 1 + Layer 2 pairing to ship? Combines the per-text Layer 1 BLOCK decisions (old index, dataset-v3 index) with the cached
Layer 2 scores of evaluation/eval_l2_compare.py (old model, dataset-v3 model) on sets none of them were trained or tuned with.

    python evaluation/eval_l2_compare.py      # fills evaluation/results/l2_compare_rows/
    python evaluation/eval_l1l2_combo.py

A text is flagged when Layer 1 says BLOCK or the Layer 2 score reaches that model's threshold ("L1 or L2", as in the other
Layer 1 + Layer 2 numbers). The consensus policy of the orchestrator is NOT applied here: this compares what each pair catches.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_l1_compare import PUBLIC_SETS, load  # noqa: E402
from eval_layer1 import wilson  # noqa: E402

RESULTS = os.path.join(BASE_DIR, "evaluation", "results")
L1_ROWS = os.path.join(RESULTS, "l1_compare_rows")
L2_ROWS = os.path.join(RESULTS, "l2_compare_rows")
OUT = os.path.join(RESULTS, "l1l2_combo.json")
INDEXES = {"l1_old": os.path.join(BASE_DIR, "models", "layer1_prefilter", "index"),
           "l1_v3": os.path.join(BASE_DIR, "models", "layer1_prefilter", "index_v3")}
THRESHOLDS = {"l2_old": json.load(open(os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts_v2_aigen", "temperature.json")))["threshold"],
              "l2_v3": json.load(open(os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts", "temperature.json")))["threshold"]}
SETS = [s for s in PUBLIC_SETS if s not in ("multijail_vi", "multijail_en")] + ["test", "external_test", "vi_test"]
PAIRS = [("l1_old", "l2_old"), ("l1_old", "l2_v3"), ("l1_v3", "l2_v3")]


def l1_blocks(tag: str, layer, name: str, frame: pd.DataFrame) -> np.ndarray:
    path = os.path.join(L1_ROWS, f"{tag}__{name}.csv")
    if os.path.exists(path):
        cached = pd.read_csv(path)
        if len(cached) == len(frame):
            return cached["block"].to_numpy().astype(bool)
    blocked = np.array([layer.check(str(t))["decision"] == "BLOCK" for t in frame["text"]])
    os.makedirs(L1_ROWS, exist_ok=True)
    pd.DataFrame({"block": blocked.astype(int)}).to_csv(path, index=False)
    print(f"[{tag}] {name}: {len(frame)} texts", flush=True)
    return blocked


def rate(hits: int, n: int) -> dict:
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def main() -> None:
    from firewall.layer1 import Layer1Prefilter

    layers = {tag: Layer1Prefilter(index_dir=path) for tag, path in INDEXES.items()}
    report = {"thresholds": THRESHOLDS, "pairs": [f"{a}+{b}" for a, b in PAIRS], "sets": {}}
    for name in SETS:
        frame = load(name)
        labels = frame["label_binary"].to_numpy().astype(int)
        l1 = {tag: l1_blocks(tag, layer, name, frame) for tag, layer in layers.items()}
        l2 = {}
        for tag in ("old", "new"):
            scores = pd.read_csv(os.path.join(L2_ROWS, f"{tag}__{name}.csv"))["score"].to_numpy()
            l2["l2_old" if tag == "old" else "l2_v3"] = scores >= THRESHOLDS["l2_old" if tag == "old" else "l2_v3"]
        entry = {"n": int(len(frame)), "pairs": {}}
        for a, b in PAIRS:
            flagged = l1[a] | l2[b]
            res = {}
            for lab, key in ((1, "attacks_flagged"), (0, "safe_flagged")):
                mask = labels == lab
                if mask.any():
                    res[key] = rate(int(flagged[mask].sum()), int(mask.sum()))
            entry["pairs"][f"{a}+{b}"] = res
        report["sets"][name] = entry
        print(f"[{name}] n={entry['n']} " + " | ".join(f"{p}: " + ", ".join(f"{k.split('_')[0]} {v['rate'] * 100:.1f}%" for k, v in r.items()) for p, r in entry["pairs"].items()), flush=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {OUT}")


if __name__ == "__main__":
    main()
