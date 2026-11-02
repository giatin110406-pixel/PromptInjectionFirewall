"""
Baselines against the system on sets that no model was trained on (BCTĐ2: Baseline).

    python evaluation/eval_baseline_v3.py

Baselines (all measured on the same texts, same metrics):
  B0  style-only classifier: logistic regression on length/case/digit/punctuation/non-ASCII ratios, trained on the TRAIN split
      of dataset v3. Threshold: 1% false-positive rate on the v3 validation split. It cannot read meaning: on a clean test set
      it should stay near chance; a high score means the set leaks its label through form (evaluation/leakage_check_v3.py).
  B1  RegexBaseline (firewall/baseline.py): the project's original baseline, hard regex patterns on the raw text.
  B2  the first-generation Layer 2 (XGBoost on 32 hand-made features, models/layer2_xgboost/model.pkl), trained on the v1
      data that had the BIPIA source leak. It also used Layer 1's similarity as a feature; here that feature is 0 (no Layer 1
      index of that time), so its numbers are a lower bound. BLOCK only, and BLOCK or ESCALATE.
System (read from the cached results of evaluation/eval_l2_compare.py and eval_l1l2_combo.py):
  L1 regex only (use_vector=False), L1 full (old index), L2 trained on dataset v2, L2 trained on dataset v3, L1 + L2 v3.

Output: evaluation/results/baseline_v3.json (rates with 95% Wilson intervals, AUC where both labels exist).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

import eval_l1_compare as c1  # noqa: E402
from eval_layer1 import wilson  # noqa: E402

R = os.path.join(BASE_DIR, "evaluation", "results")
CACHE = os.path.join(R, "baseline_v3_rows")
OUT = os.path.join(R, "baseline_v3.json")
V3 = os.path.join(BASE_DIR, "data", "processed_public")
SETS = ["deepset", "grayswan_ipi", "holdout_tensortrust", "holdout_injecagent_base", "holdout_injecagent_enhanced", "holdout_dolly_instr",
        "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc", "test", "external_test", "vi_test"]
THR_OLD = json.load(open(os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts_v2_aigen", "temperature.json")))["threshold"]
THR_NEW = json.load(open(os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts", "temperature.json")))["threshold"]


def rate(hits, n):
    return {"n": int(n), "hits": int(hits), "rate": round(hits / n, 4) if n else None, "ci95": wilson(int(hits), int(n))}


def fit_b0():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from data.scripts.audit_leakage import style_features

    tr = pd.read_csv(os.path.join(V3, "dataset_v2_train.csv"), keep_default_na=False)
    va = pd.read_csv(os.path.join(V3, "dataset_v2_validation.csv"), keep_default_na=False)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    model.fit(style_features(tr["text"]), tr["label_binary"])
    pv = model.predict_proba(style_features(va["text"]))[:, 1]
    safe = np.sort(pv[va["label_binary"].to_numpy() == 0])
    thr = float(safe[int(np.ceil(0.99 * len(safe))) - 1])          # 1% of the validation safe texts score above it
    return model, thr, style_features


def per_text(name, frame, b0, regex, l1r, v1):
    path = os.path.join(CACHE, f"{name}.csv")
    if os.path.exists(path):
        cached = pd.read_csv(path)
        if len(cached) == len(frame):
            return cached
    model, thr, feats = b0
    texts = [str(t) for t in frame["text"]]
    out = pd.DataFrame({
        "b0_score": model.predict_proba(feats(pd.Series(texts)))[:, 1],
        "b1_regex": [int(regex.predict(t)["decision"] == "BLOCK") for t in texts],
        "l1_regex_only": [int(l1r.check(t)["decision"] == "BLOCK") for t in texts]})
    d1 = [v1.check(t, top_similarity=0.0)["decision"] for t in texts] if v1 is not None else ["n/a"] * len(texts)
    out["b2_block"] = [int(d == "BLOCK") for d in d1]
    out["b2_block_or_escalate"] = [int(d in ("BLOCK", "ESCALATE")) for d in d1]
    os.makedirs(CACHE, exist_ok=True)
    out.to_csv(path, index=False)
    print(f"[{name}] {len(frame)} texts", flush=True)
    return out


def main() -> None:
    from firewall.baseline import RegexBaseline
    from firewall.layer1 import Layer1Prefilter
    from sklearn.metrics import roc_auc_score

    b0 = fit_b0()
    thr_b0 = b0[1]
    regex, l1r = RegexBaseline(), Layer1Prefilter(use_vector=False)
    try:
        from firewall.layer2 import Layer2Classifier
        v1 = Layer2Classifier()
        assert v1.model is not None
    except Exception as exc:
        print("[WARN] v1 XGBoost model not usable:", exc)
        v1 = None
    report = {"b0_threshold": round(thr_b0, 4), "thresholds": {"l2_v2": THR_OLD, "l2_v3": THR_NEW},
              "v1_xgboost_usable": v1 is not None, "sets": {}}
    for name in SETS:
        frame = c1.load(name)
        y = frame["label_binary"].to_numpy().astype(int)
        t = per_text(name, frame, b0, regex, l1r, v1)
        l1 = pd.read_csv(os.path.join(R, "l1_compare_rows", f"l1_old__{name}.csv"))["block"].to_numpy().astype(bool)
        s_old = pd.read_csv(os.path.join(R, "l2_compare_rows", f"old__{name}.csv"))["score"].to_numpy()
        s_new = pd.read_csv(os.path.join(R, "l2_compare_rows", f"new__{name}.csv"))["score"].to_numpy()
        flags = {
            "B0_style_only": t["b0_score"].to_numpy() >= thr_b0,
            "B1_regex_baseline": t["b1_regex"].to_numpy() == 1,
            "B2_v1_xgboost_block": t["b2_block"].to_numpy() == 1,
            "B2_v1_xgboost_block_or_escalate": t["b2_block_or_escalate"].to_numpy() == 1,
            "L1_regex_only": t["l1_regex_only"].to_numpy() == 1,
            "L1_full_old_index": l1,
            "L2_trained_on_v2": s_old >= THR_OLD,
            "L2_trained_on_v3": s_new >= THR_NEW,
            "L1_plus_L2_v3": l1 | (s_new >= THR_NEW)}
        entry = {"n": int(len(frame)), "labels": {str(k): int(v) for k, v in pd.Series(y).value_counts().items()}, "methods": {}, "auc": {}}
        for m, f in flags.items():
            e = {}
            if (y == 1).any():
                e["attacks_flagged"] = rate(int(f[y == 1].sum()), int((y == 1).sum()))
            if (y == 0).any():
                e["safe_flagged"] = rate(int(f[y == 0].sum()), int((y == 0).sum()))
            entry["methods"][m] = e
        if len(set(y.tolist())) == 2:       # raw AUC: the direction is NOT re-chosen on the test set
            entry["auc"] = {"B0_style_only": round(float(roc_auc_score(y, t["b0_score"])), 4),
                            "L2_trained_on_v2": round(float(roc_auc_score(y, s_old)), 4), "L2_trained_on_v3": round(float(roc_auc_score(y, s_new)), 4)}
        report["sets"][name] = entry
        print(name, {m: (round(e.get("attacks_flagged", {}).get("rate") or 0, 3), round(e.get("safe_flagged", {}).get("rate") or 0, 3)) for m, e in entry["methods"].items()}, entry["auc"], flush=True)
    # B0 on the splits of dataset v3 itself (same distribution as its training data)
    model, thr, feats = b0
    report["b0_on_dataset_v3"] = {}
    for split in ("validation", "test"):
        df = pd.read_csv(os.path.join(V3, f"dataset_v2_{split}.csv"), keep_default_na=False)
        yy = df["label_binary"].to_numpy().astype(int)
        pp = model.predict_proba(feats(df["text"]))[:, 1]
        ff = pp >= thr
        report["b0_on_dataset_v3"][split] = {"n": int(len(df)), "auc": round(float(roc_auc_score(yy, pp)), 4),
                                              "attacks_flagged": rate(int(ff[yy == 1].sum()), int((yy == 1).sum())),
                                              "safe_flagged": rate(int(ff[yy == 0].sum()), int((yy == 0).sum()))}
        print("B0 on v3", split, report["b0_on_dataset_v3"][split]["auc"], flush=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
