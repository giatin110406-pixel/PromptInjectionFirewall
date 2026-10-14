"""
Compare two Layer 2 checkpoints (old: trained on dataset v2, AI-generated; new: trained on dataset v3, public data)
on sets that NEITHER model was trained on or tuned with.

    python evaluation/eval_l2_compare.py                                   # old (artifacts_v2_aigen) vs v3 (artifacts)
    python evaluation/eval_l2_compare.py --new path/to/artifacts --sets deepset,grayswan_ipi

Each model uses its own temperature and threshold (temperature.json). Texts are scored per document: the highest score of
the 200-token windows, as in production. Rates carry 95% Wilson intervals; AUC is given when a set has both labels.

Sets (see docs/dataset_layer_map_v3.md):
  clean for both models   deepset, grayswan_ipi, multijail_vi, multijail_en, the held-out parts (holdout_*) of Tensor Trust,
                          InjecAgent, Dolly, XQuAD-vi, and the old evaluation sets (dataset_v2 test, tmdeptrai external, vi_test_v1)
  NOT used here           the full Dolly, XQuAD, Tensor Trust and InjecAgent sets: the new model was trained on them.
Scores are cached per model and set in evaluation/results/l2_compare_rows/.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from eval_layer1 import load_set, wilson  # noqa: E402

PUBLIC = os.path.join(BASE_DIR, "data", "eval", "public")
CACHE = os.path.join(BASE_DIR, "evaluation", "results", "l2_compare_rows")
OUT = os.path.join(BASE_DIR, "evaluation", "results", "l2_compare.json")
OLD_DEFAULT = os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts_v2_aigen")
NEW_DEFAULT = os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts")
PUBLIC_SETS = ["deepset", "grayswan_ipi", "multijail_vi", "multijail_en", "holdout_tensortrust", "holdout_injecagent_base",
               "holdout_injecagent_enhanced", "holdout_dolly_instr", "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc"]
OLD_SETS = ["test", "external_dev", "external_test", "vi_dev", "vi_test"]


def load(name: str) -> pd.DataFrame:
    if name in OLD_SETS:
        return load_set(name)
    return pd.read_csv(os.path.join(PUBLIC, f"{name}.csv"), keep_default_na=False)


def score_set(tag: str, classifier, name: str, frame: pd.DataFrame) -> np.ndarray:
    path = os.path.join(CACHE, f"{tag}__{name}.csv")
    if os.path.exists(path):
        cached = pd.read_csv(path)
        if len(cached) == len(frame):
            return cached["score"].to_numpy()
    started = time.time()
    scores = np.array([max(classifier.window_scores(str(t))) for t in frame["text"]])
    os.makedirs(CACHE, exist_ok=True)
    pd.DataFrame({"score": scores}).to_csv(path, index=False)
    print(f"[{tag}] {name}: {len(frame)} texts in {time.time() - started:.0f}s", flush=True)
    return scores


def rate(hits: int, n: int) -> dict:
    return {"n": n, "hits": hits, "rate": round(hits / n, 4) if n else None, "ci95": wilson(hits, n)}


def evaluate(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    flagged = scores >= threshold
    out = {}
    for lab, key in ((1, "attacks_flagged"), (0, "safe_flagged")):
        mask = labels == lab
        if mask.any():
            out[key] = rate(int(flagged[mask].sum()), int(mask.sum()))
    if len(set(labels.tolist())) == 2:
        from sklearn.metrics import roc_auc_score
        out["auc"] = round(float(roc_auc_score(labels, scores)), 4)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default=OLD_DEFAULT)
    parser.add_argument("--new", default=NEW_DEFAULT)
    parser.add_argument("--sets", help="comma-separated (default: all)")
    args = parser.parse_args()
    names = [s.strip() for s in args.sets.split(",")] if args.sets else PUBLIC_SETS + OLD_SETS

    from firewall.classifier import MultilingualClassifier

    models = {}
    for tag, path in (("old", args.old), ("new", args.new)):
        if not os.path.exists(os.path.join(path, "checkpoint")):
            print(f"[WARN] {tag}: no checkpoint in {path}, skipped")
            continue
        clf = MultilingualClassifier(artifacts_dir=path)
        assert clf.model is not None, clf.error
        models[tag] = clf
        print(f"[INFO] {tag}: {path} threshold={clf.threshold} temperature={clf.temperature:.4f}", flush=True)

    report = {"models": {t: {"artifacts": getattr(m, "artifacts_dir", ""), "threshold": m.threshold, "temperature": m.temperature} for t, m in models.items()},
              "sets": {}}
    for name in names:
        frame = load(name)
        labels = frame["label_binary"].to_numpy().astype(int)
        entry = {"n": int(len(frame)), "labels": {str(k): int(v) for k, v in pd.Series(labels).value_counts().items()}}
        for tag, clf in models.items():
            entry[tag] = evaluate(score_set(tag, clf, name, frame), labels, clf.threshold)
        report["sets"][name] = entry
        line = " | ".join(f"{tag}: " + ", ".join(f"{k.split('_')[0]} {v['rate'] * 100:.1f}%" for k, v in entry[tag].items() if isinstance(v, dict)) for tag in models)
        print(f"[{name}] n={entry['n']} {line}", flush=True)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {OUT}")


if __name__ == "__main__":
    main()
