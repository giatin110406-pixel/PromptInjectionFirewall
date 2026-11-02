"""
Data leakage check for dataset v3 and for the public evaluation sets (BCTĐ2: Data Leakage Check).

    python evaluation/leakage_check_v3.py

What it measures (every number is written to evaluation/results/leakage_v3.json):
  1. Length and style leakage: AUC of the text length alone and of a style-only classifier (no vocabulary: length, case,
     digits, punctuation, non-ASCII...; 5-fold cross-validated), for the whole dataset, each split, each source and each
     language, next to the "noise floor" (the same classifier on shuffled labels). 0.5 = the label cannot be guessed.
     Same tool and same threshold (0.80) as data/scripts/audit_leakage.py, which produced the dataset v2 numbers.
  2. Label balance per (split, language): language must not tell the label.
  3. Duplicates across splits: exact copies of a text, and near duplicates (character n-gram TF-IDF cosine >= 0.80) of the
     sentences that were inserted into the base texts, between train and validation/test.
  4. Held-out and public evaluation sets against what the model was trained on, and against each other.
Nothing here trains or tunes anything.
"""
import json
import os
import re
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from data.scripts.audit_leakage import MIN_PER_CLASS, _auc_both_directions, style_features  # noqa: E402

V3 = os.path.join(BASE_DIR, "data", "processed_public")
PUBLIC = os.path.join(BASE_DIR, "data", "eval", "public")
OUT = os.path.join(BASE_DIR, "evaluation", "results", "leakage_v3.json")
NEAR = 0.80
EVAL_SETS = ["deepset", "grayswan_ipi", "multijail_vi", "multijail_en", "holdout_tensortrust", "holdout_injecagent_base",
             "holdout_dolly_instr", "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc"]


def norm_key(text) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def aucs(X: pd.DataFrame, lengths: np.ndarray, y: np.ndarray, repeats: int = 5, seed: int = 42):
    """(length AUC, style AUC, style noise floor) for the rows given; None when a class is too small."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    counts = pd.Series(y).value_counts()
    if len(counts) < 2 or counts.min() < MIN_PER_CLASS:
        return None, None, None
    length = float(_auc_both_directions(roc_auc_score(y, lengths)))
    cv = StratifiedKFold(n_splits=int(min(5, counts.min())), shuffle=True, random_state=seed)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))

    def cv_auc(labels):
        proba = cross_val_predict(model, X, labels, cv=cv, method="predict_proba")[:, 1]
        return float(_auc_both_directions(roc_auc_score(labels, proba)))

    style = cv_auc(y)
    rng = np.random.default_rng(0)
    floor = float(np.mean([cv_auc(rng.permutation(y)) for _ in range(repeats)]))
    return length, style, floor


def row(values):
    return None if values[0] is None else {"length_auc": round(values[0], 4), "style_auc": round(values[1], 4), "noise_floor": round(values[2], 4)}


def main() -> None:
    frames = {s: pd.read_csv(os.path.join(V3, f"dataset_v2_{s}.csv"), keep_default_na=False) for s in ("train", "validation", "test")}
    allf = pd.concat([f.assign(split=s) for s, f in frames.items()], ignore_index=True)
    X = style_features(allf["text"])
    lengths = allf["text"].str.len().to_numpy()
    y = allf["label_binary"].to_numpy().astype(int)
    report = {"dataset": "data/processed_public (dataset v3)", "rows": {s: len(f) for s, f in frames.items()}, "near_threshold": NEAR,
              "flag_threshold": 0.80}

    # ---- 1. length and style
    def sub(mask):
        m = np.asarray(mask)
        return aucs(X[m].reset_index(drop=True), lengths[m], y[m])

    leak = {"all": row(sub(np.ones(len(allf), dtype=bool)))}
    for s in frames:
        leak[f"split:{s}"] = row(sub(allf["split"] == s))
    for src, g in allf.groupby("source"):
        leak[f"source:{src}"] = row(sub(allf["source"] == src)) or {"note": "một nhãn duy nhất, không đo được"}
        leak[f"source:{src}"]["n"] = int(len(g))
    for lg in ("en", "mixed", "vi"):
        leak[f"lang:{lg}"] = row(sub(allf["lang"] == lg))
    report["length_style_auc"] = leak
    print("[INFO] length/style AUC done", flush=True)

    # length statistics per label
    report["length_chars"] = {s: {str(int(k)): {"mean": round(float(g.text.str.len().mean()), 1), "median": round(float(g.text.str.len().median()), 1)}
                                  for k, g in f.groupby("label_binary")} for s, f in frames.items()}

    # ---- 2. label balance per (split, language)
    report["label_by_split_lang"] = {f"{s}/{lg}": {str(int(k)): int(v) for k, v in g.label_binary.value_counts().items()}
                                     for (s, lg), g in allf.groupby(["split", "lang"])}

    # ---- 3. duplicates across splits
    keys = allf["text"].map(norm_key)
    allf["_k"] = keys
    exact = {}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        exact[f"{a} vs {b}"] = int(len(set(allf[allf.split == a]._k) & set(allf[allf.split == b]._k)))
    report["exact_duplicate_texts_across_splits"] = exact
    ids = allf.groupby("orig_id").split.nunique()
    tpl = allf[allf.template_id != ""].groupby("template_id").split.nunique()
    report["ids_in_more_than_one_split"] = {"orig_id": int((ids > 1).sum()), "template_id": int((tpl > 1).sum())}

    from sklearn.feature_extraction.text import TfidfVectorizer

    def pool_strings(frame):
        out = list(frame.loc[frame.insert_text != "", "insert_text"].unique())
        raw = frame[frame.variant.isin(["raw", "pure_attack", "clean"]) & ~frame.source.str.endswith("_doc")]
        out += [t[:600] for t in raw["text"]]
        docs = frame[frame.variant.eq("clean") & frame.source.str.endswith("_doc")]
        out += [t.split("External context:\n", 1)[-1][:600] for t in docs["text"]]
        return list(dict.fromkeys(s for s in out if len(s) >= 15))

    pools = {s: pool_strings(f) for s, f in frames.items()}
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    vec.fit(sum(pools.values(), []))
    train_m = vec.transform(pools["train"])

    def near_share(strings, matrix=train_m):
        if not strings:
            return {"n": 0, "near": 0, "share": None}
        hits = 0
        m = vec.transform(strings)
        for i in range(0, m.shape[0], 500):
            best = np.asarray((m[i:i + 500] @ matrix.T).max(axis=1).todense()).ravel()
            hits += int((best >= NEAR).sum())
        return {"n": len(strings), "near": hits, "share": round(hits / len(strings), 4)}

    # sentences inserted into base texts, and raw/base strings, of validation and test against train
    ins = {}
    for s in ("validation", "test"):
        f = frames[s]
        ins[f"insert_attack:{s}"] = near_share(list(f.loc[(f.insert_text != "") & (f.label_binary == 1), "insert_text"].unique()))
        ins[f"insert_benign:{s}"] = near_share(list(f.loc[(f.insert_text != "") & (f.label_binary == 0), "insert_text"].unique()))
        ins[f"base_and_raw_texts:{s}"] = near_share(pools[s])
    report["near_duplicates_vs_train"] = ins
    print("[INFO] cross-split duplicates done", flush=True)

    # ---- 4. evaluation sets
    sets = {n: pd.read_csv(os.path.join(PUBLIC, f"{n}.csv"), keep_default_na=False) for n in EVAL_SETS}
    ev = {}
    for n, f in sets.items():
        strings = [str(t)[:600] for t in f["text"]]
        exact_hits = int(sum(norm_key(t) in set(map(norm_key, pools["train"])) for t in strings)) if len(strings) < 3000 else None
        ev[n] = {"rows": int(len(f)), "near_duplicate_of_train": near_share(strings), "exact_in_train_pool": exact_hits}
    report["eval_sets_vs_v3_train"] = ev

    cross = {}
    for a in EVAL_SETS:
        others = [str(t)[:600] for b in EVAL_SETS if b != a for t in sets[b]["text"]]
        om = vec.transform(others)
        cross[a] = near_share([str(t)[:600] for t in sets[a]["text"]], om)
    report["eval_sets_vs_other_eval_sets"] = cross

    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {OUT}")
    for k, v in leak.items():
        print(f"  {k:28s} {v}")
    print("exact dup across splits:", exact, "| ids in >1 split:", report["ids_in_more_than_one_split"])
    for k, v in ins.items():
        print(" ", k, v)
    for k, v in ev.items():
        print(" ", k, v["near_duplicate_of_train"])
    for k, v in cross.items():
        print("  cross", k, v)


if __name__ == "__main__":
    main()
