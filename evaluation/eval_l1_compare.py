"""
Compare Layer 1 (regex + semantic index) built from dataset v2 (old index) with the one built from dataset v3 (public data),
each with its own thresholds, on sets neither index was built from or tuned with.

    python evaluation/eval_l1_compare.py                                  # old index vs models/layer1_prefilter/index_v3
    python evaluation/eval_l1_compare.py --new models/layer1_prefilter/index_v3_noseed

BLOCK is the decision reported (as in the other Layer 1 numbers). Rates carry 95% Wilson intervals.
Sets: the public sets and held-out parts of docs/dataset_layer_map_v3.md, the dataset v3 test split, the old dataset v2 test,
tmdeptrai external and vi_test_v1 (the last two have dev halves that were used for thresholds; only the test halves are used here).
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

import eval_layer1  # noqa: E402
from eval_layer1 import load_set, wilson  # noqa: E402

PUBLIC = os.path.join(BASE_DIR, "data", "eval", "public")
OUT = os.path.join(BASE_DIR, "evaluation", "results", "l1_compare.json")
V3_TEST = os.path.join(BASE_DIR, "data", "processed_public", "dataset_v2_test.csv")
PUBLIC_SETS = ["deepset", "grayswan_ipi", "multijail_vi", "multijail_en", "holdout_tensortrust", "holdout_injecagent_base",
               "holdout_injecagent_enhanced", "holdout_dolly_instr", "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc"]
OLD_SETS = ["test", "external_test", "vi_test"]


def load(name: str) -> pd.DataFrame:
    if name == "v3_test":
        return pd.read_csv(V3_TEST, keep_default_na=False)
    if name in OLD_SETS:
        return load_set(name)
    return pd.read_csv(os.path.join(PUBLIC, f"{name}.csv"), keep_default_na=False)


def rate(hits: int, n: int) -> dict:
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default=os.path.join(BASE_DIR, "models", "layer1_prefilter", "index"))
    parser.add_argument("--new", default=os.path.join(BASE_DIR, "models", "layer1_prefilter", "index_v3"))
    args = parser.parse_args()

    from firewall.layer1 import Layer1Prefilter

    layers = {}
    for tag, path in (("old", args.old), ("new", args.new)):
        layer = Layer1Prefilter(index_dir=path)
        assert not layer.degraded, layer.vector_error
        layers[tag] = layer
        t = layer.index.thresholds
        print(f"[INFO] {tag}: {path} entries={layer.index.meta['n_entries']} block_sim={t.block_sim} margin={t.block_margin} escalate_sim={t.escalate_sim}", flush=True)

    report = {"indexes": {tag: {"dir": os.path.relpath(p, BASE_DIR), "entries": layers[tag].index.meta["n_entries"],
                                "thresholds": layers[tag].index.thresholds.__dict__} for tag, p in (("old", args.old), ("new", args.new))},
              "sets": {}}
    for name in PUBLIC_SETS + ["v3_test"] + OLD_SETS:
        frame = load(name)
        labels = frame["label_binary"].to_numpy().astype(int)
        entry = {"n": int(len(frame)), "labels": {str(k): int(v) for k, v in pd.Series(labels).value_counts().items()}}
        for tag, layer in layers.items():
            blocked = np.array([layer.check(str(t))["decision"] == "BLOCK" for t in frame["text"]])
            res = {}
            for lab, key in ((1, "attacks_blocked"), (0, "safe_blocked")):
                mask = labels == lab
                if mask.any():
                    res[key] = rate(int(blocked[mask].sum()), int(mask.sum()))
            entry[tag] = res
        report["sets"][name] = entry
        line = " | ".join(f"{tag}: " + ", ".join(f"{k.split('_')[0]} {v['rate'] * 100:.1f}%" for k, v in entry[tag].items()) for tag in layers)
        print(f"[{name}] n={entry['n']} {line}", flush=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {OUT}")


if __name__ == "__main__":
    main()
