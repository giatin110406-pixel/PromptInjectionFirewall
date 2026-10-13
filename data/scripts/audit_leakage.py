"""
Leakage audit for prompt-injection training data (P2-T1).

A dataset leaks when a model can predict the label from something that is not the
attack itself. The v1 Layer 3 data did: every malicious row came from BIPIA and every
safe row from GPT-4o-mini, so "which source" decided the label.

Per source this script reports:
- label counts and whether the source holds a single label,
- text length per label and how well length alone separates the labels (AUC),
- a style-only classifier (no vocabulary): length, case, digit, punctuation ratios,
- language mix, including German/Spanish text left inside a "Vietnamese" source,
- exact and lexical near-duplicate overlap with a reference source (default: deepset),
- a "same shape as" check that exposes a translated copy of another dataset.

Across sources it reports label purity (does the source decide the label?) and the
style-only AUC on the pooled data.

A lexical overlap check cannot see across languages. A Vietnamese translation of an
English dataset will not match it by character n-grams, which is why the shape check
exists. Add an embedding-based check before trusting "no overlap" for translated data.

Usage:
    python data/scripts/audit_leakage.py
    python data/scripts/audit_leakage.py --sources deepset,rikka,tmdeptrai --offline
    python data/scripts/audit_leakage.py --csv mine=path/to/file.csv   # text,label_binary
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.vietnamese_norm import detect_language  # noqa: E402

DEFAULT_OUT = os.path.join(BASE_DIR, "evaluation", "results", "leakage_report.json")
DEFAULT_BIPIA_JSONL = os.path.join(BASE_DIR, "dataset_for_huggingface.jsonl")

# A source is flagged when length or style alone separates the labels this well.
STYLE_AUC_LEAK = 0.80
LENGTH_AUC_LEAK = 0.80
FOREIGN_RATE_FLAG = 0.05
DUPLICATE_RATE_FLAG = 0.05
MIN_PER_CLASS = 30  # below this, a cross-validated AUC is not meaningful

_GERMAN = re.compile(
    r"\b(ich|und|der|die|das|nicht|ist|ein|eine|zu|mit|für|wie|sie|mir|auf|bei|kann|würde|haben)\b",
    re.IGNORECASE,
)
_SPANISH = re.compile(
    r"\b(que|los|las|una|por|para|como|pero|está|usted|puedo|quiero|si)\b", re.IGNORECASE
)


# ----------------------------------------------------------------------------
# Loaders: each returns a frame with at least `text` and `label_binary` (0 safe, 1 attack)
# ----------------------------------------------------------------------------
def _normalize_label(value: Any) -> Optional[int]:
    if isinstance(value, (int, np.integer, bool)):
        return int(value)
    text = str(value).strip().lower()
    if text in {"1", "injection", "malicious", "attack", "unsafe", "jailbreak"}:
        return 1
    if text in {"0", "benign", "safe", "normal", "legitimate"}:
        return 0
    return None


def _frame(records: List[Dict[str, Any]], source: str) -> pd.DataFrame:
    rows = []
    for record in records:
        label = _normalize_label(record.get("label_binary", record.get("label")))
        text = record.get("text")
        if label is None or not isinstance(text, str) or not text.strip():
            continue
        rows.append({"text": text.strip(), "label_binary": label, "source": source})
    return pd.DataFrame(rows, columns=["text", "label_binary", "source"])


def load_hf(dataset_id: str, source: str) -> pd.DataFrame:
    from datasets import load_dataset

    ds = load_dataset(dataset_id)
    records: List[Dict[str, Any]] = []
    for split in ds.keys():
        records.extend(dict(r) for r in ds[split])
    return _frame(records, source)


def load_hf_jsonl(dataset_id: str, files: List[str], source: str) -> pd.DataFrame:
    """Fetch raw jsonl files from a Hub dataset repo (works when load_dataset cannot resolve)."""
    from huggingface_hub import hf_hub_download

    records: List[Dict[str, Any]] = []
    for name in files:
        path = hf_hub_download(dataset_id, name, repo_type="dataset")
        with open(path, "r", encoding="utf-8") as handle:
            records.extend(json.loads(line) for line in handle if line.strip())
    return _frame(records, source)


def load_csv(path: str, source: str) -> pd.DataFrame:
    return _frame(pd.read_csv(path).to_dict("records"), source)


def load_bipia(path: str, source: str = "bipia_gpt") -> pd.DataFrame:
    """BIPIA-GPT jsonl; keep the original upstream source so the confound is visible."""
    from data.scripts.prepare_real_datasets import _load_bipia_gpt_jsonl

    frame = _load_bipia_gpt_jsonl(path)
    frame = frame.rename(columns={"dataset_source": "origin"})
    frame["source"] = source
    return frame[["text", "label_binary", "source", "origin"]]


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def style_features(texts: pd.Series) -> pd.DataFrame:
    """Vocabulary-free features: how the text looks, not what it says."""
    def one(text: str) -> Dict[str, float]:
        chars = max(len(text), 1)
        words = text.split()
        alpha = sum(c.isalpha() for c in text) or 1
        return {
            "n_chars": float(len(text)),
            "n_words": float(len(words)),
            "avg_word_len": float(np.mean([len(w) for w in words])) if words else 0.0,
            "upper_ratio": sum(c.isupper() for c in text) / alpha,
            "digit_ratio": sum(c.isdigit() for c in text) / chars,
            "punct_ratio": sum((not c.isalnum()) and (not c.isspace()) for c in text) / chars,
            "newlines": float(text.count("\n")),
            "non_ascii_ratio": sum(ord(c) > 127 for c in text) / chars,
        }

    return pd.DataFrame([one(t) for t in texts.astype(str)], index=texts.index)


def _auc_both_directions(auc: float) -> float:
    """Separability regardless of direction: 0.5 = none, 1.0 = perfect."""
    return max(auc, 1.0 - auc)


def length_auc(frame: pd.DataFrame) -> Optional[float]:
    from sklearn.metrics import roc_auc_score

    if frame["label_binary"].nunique() < 2:
        return None
    return float(_auc_both_directions(roc_auc_score(frame["label_binary"], frame["text"].str.len())))


def style_auc(frame: pd.DataFrame, folds: int = 5, seed: int = 42) -> Optional[float]:
    """Cross-validated AUC of a style-only classifier predicting the label."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    counts = frame["label_binary"].value_counts()
    if len(counts) < 2 or counts.min() < MIN_PER_CLASS:
        return None
    X = style_features(frame["text"])
    y = frame["label_binary"].to_numpy()
    n_splits = int(min(folds, counts.min()))
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    proba = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
    return float(_auc_both_directions(roc_auc_score(y, proba)))


def style_auc_noise_floor(frame: pd.DataFrame, repeats: int = 5, seed: int = 0) -> Optional[float]:
    """
    What `style_auc` reports when the labels carry NO signal (shuffled). Taking the better of the
    two directions inflates the number on small samples: pure noise measured 0.585 at n=60,
    0.566 at n=160, 0.52 at n=400, 0.51 at n=2000. Read `style_auc` against this floor.
    """
    if style_auc(frame) is None:
        return None
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(repeats):
        shuffled = frame.assign(label_binary=rng.permutation(frame["label_binary"].to_numpy()))
        value = style_auc(shuffled)
        if value is not None:
            values.append(value)
    return float(np.mean(values)) if values else None


def length_stats(frame: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for label, group in frame.groupby("label_binary"):
        lengths = group["text"].str.len()
        out[str(int(label))] = {
            "mean": round(float(lengths.mean()), 1),
            "median": round(float(lengths.median()), 1),
            "p95": round(float(lengths.quantile(0.95)), 1),
        }
    return out


def language_mix(frame: pd.DataFrame) -> Dict[str, Any]:
    """Language per label, plus German/Spanish text hiding inside the source."""
    languages = frame["text"].map(detect_language)
    german = frame["text"].map(lambda t: len(_GERMAN.findall(t)) >= 3)
    spanish = frame["text"].map(lambda t: len(_SPANISH.findall(t)) >= 3)
    foreign = german | spanish
    by_label = {}
    for label, idx in frame.groupby("label_binary").groups.items():
        by_label[str(int(label))] = round(float(foreign.loc[idx].mean()), 3)
    return {
        "detected": {k: int(v) for k, v in languages.value_counts().items()},
        "foreign_rate": round(float(foreign.mean()), 3),
        "foreign_rate_by_label": by_label,
    }


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def overlap_with_reference(
    frame: pd.DataFrame, reference: pd.DataFrame, sample: int = 5000, near_threshold: float = 0.8
) -> Dict[str, float]:
    """Exact and lexical near-duplicate rate against the reference texts (same language only)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    ref_keys = {_normalize_key(t) for t in reference["text"]}
    keys = frame["text"].map(_normalize_key)
    exact = float(keys.isin(ref_keys).mean())

    subset = frame["text"] if len(frame) <= sample else frame["text"].sample(sample, random_state=42)
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    vectorizer.fit(list(reference["text"]) + list(subset))
    ref_matrix = vectorizer.transform(reference["text"])
    near_hits = 0
    for start in range(0, len(subset), 1000):
        chunk = vectorizer.transform(subset.iloc[start:start + 1000])
        best = (chunk @ ref_matrix.T).max(axis=1).toarray().ravel()
        near_hits += int((best >= near_threshold).sum())
    return {"exact_rate": round(exact, 4), "near_duplicate_rate": round(near_hits / max(len(subset), 1), 4)}


def dataset_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for text, label in sorted(zip(frame["text"].astype(str), frame["label_binary"].astype(int))):
        digest.update(f"{label}\t{text}\n".encode("utf-8"))
    return digest.hexdigest()


def audit_frame(
    frame: pd.DataFrame, name: str, reference: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    counts = frame["label_binary"].value_counts()
    report: Dict[str, Any] = {
        "name": name,
        "n": int(len(frame)),
        "label_counts": {str(int(k)): int(v) for k, v in counts.items()},
        "single_label": bool(len(counts) < 2),
        "duplicate_texts_within": int(frame["text"].map(_normalize_key).duplicated().sum()),
        "length": length_stats(frame),
        "length_auc": length_auc(frame),
        "style_auc": style_auc(frame),
        "style_auc_noise_floor": style_auc_noise_floor(frame),
        "language": language_mix(frame),
        "dataset_sha256": dataset_hash(frame),
    }
    if reference is not None and name != "deepset":
        report["overlap_with_reference"] = overlap_with_reference(frame, reference)

    flags: List[str] = []
    if report["single_label"]:
        flags.append("single_label_source")
    if report["length_auc"] is not None and report["length_auc"] >= LENGTH_AUC_LEAK:
        flags.append("length_leak")
    if report["style_auc"] is not None and report["style_auc"] >= STYLE_AUC_LEAK:
        flags.append("style_leak")
    if report["language"]["foreign_rate"] >= FOREIGN_RATE_FLAG:
        flags.append("mixed_foreign_language")
    overlap = report.get("overlap_with_reference")
    if overlap and max(overlap.values()) >= DUPLICATE_RATE_FLAG:
        flags.append("duplicate_with_reference")
    if "origin" in frame.columns:
        report["origins"] = {str(k): int(v) for k, v in frame["origin"].value_counts().items()}
        confound = audit_origin_confound(frame)
        report["origin_confound"] = confound
        if confound and confound["origin_determines_label"]:
            flags.append("origin_determines_label")
    report["flags"] = flags
    report["leaky"] = any(
        f in flags for f in ("single_label_source", "length_leak", "style_leak", "origin_determines_label")
    )
    return report


def shape_matches(reports: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Sources with identical size and label counts: strong sign of a translated copy."""
    seen: Dict[Any, str] = {}
    matches: Dict[str, str] = {}
    for name, rep in reports.items():
        key = (rep["n"], tuple(sorted(rep["label_counts"].items())))
        if key in seen and rep["n"] >= 50:
            matches[name] = seen[key]
        else:
            seen.setdefault(key, name)
    return matches


def audit_pooled(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Does the source decide the label, and does style alone predict it on the pool?"""
    pooled = pd.concat(frames.values(), ignore_index=True)
    crosstab = pd.crosstab(pooled["source"], pooled["label_binary"])
    majority = crosstab.max(axis=1).sum() / max(len(pooled), 1)
    return {
        "n": int(len(pooled)),
        "source_label_crosstab": {
            src: {str(int(k)): int(v) for k, v in row.items()} for src, row in crosstab.iterrows()
        },
        "label_purity_by_source": round(float(majority), 4),
        "style_auc_pooled": style_auc(pooled),
    }


def audit_origin_confound(frame: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """For BIPIA-style data: does the upstream `origin` determine the label?"""
    if "origin" not in frame.columns:
        return None
    crosstab = pd.crosstab(frame["origin"], frame["label_binary"])
    purity = float(crosstab.max(axis=1).sum() / max(len(frame), 1))
    return {
        "origin_label_crosstab": {
            str(o): {str(int(k)): int(v) for k, v in row.items()} for o, row in crosstab.iterrows()
        },
        "origin_label_purity": round(purity, 4),
        "origin_determines_label": bool(purity >= 0.99 and crosstab.shape[0] >= 2),
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=BASE_DIR, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def build_loaders(args: argparse.Namespace) -> Dict[str, Callable[[], pd.DataFrame]]:
    loaders: Dict[str, Callable[[], pd.DataFrame]] = {}
    if not args.offline:
        loaders["deepset"] = lambda: load_hf("deepset/prompt-injections", "deepset")
        loaders["rikka"] = lambda: load_hf("rikka-snow/prompt-injection-vi", "rikka")
        loaders["tmdeptrai"] = lambda: load_hf_jsonl(
            "tmdeptrai3012/prompt-injection-dataset-vi-en", ["train.jsonl", "test.jsonl"], "tmdeptrai"
        )
        loaders["dangvansam"] = lambda: load_hf("dangvansam/vietnamese-prompt-injection", "dangvansam")
    if os.path.exists(args.bipia_jsonl):
        loaders["bipia"] = lambda: load_bipia(args.bipia_jsonl)
    for spec in args.csv or []:
        name, _, path = spec.partition("=")
        loaders[name] = (lambda p=path, n=name: load_csv(p, n))
    return loaders


def run(args: argparse.Namespace) -> Dict[str, Any]:
    loaders = build_loaders(args)
    wanted = [s.strip() for s in args.sources.split(",")] if args.sources else list(loaders)
    frames: Dict[str, pd.DataFrame] = {}
    unavailable: Dict[str, str] = {}
    for name in wanted:
        if name not in loaders:
            unavailable[name] = "no loader (offline, missing file, or unknown name)"
            continue
        try:
            frame = loaders[name]()
            if frame.empty:
                raise ValueError("loaded zero usable rows")
            frames[name] = frame
        except Exception as exc:
            unavailable[name] = f"{type(exc).__name__}: {str(exc)[:160]}"

    reference = frames.get("deepset")
    reports = {name: audit_frame(frame, name, reference) for name, frame in frames.items()}
    for name, twin in shape_matches(reports).items():
        reports[name]["flags"].append(f"same_shape_as:{twin}")
        reports[name]["possible_translation_of"] = twin

    result: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "thresholds": {
            "style_auc_leak": STYLE_AUC_LEAK,
            "length_auc_leak": LENGTH_AUC_LEAK,
            "foreign_rate_flag": FOREIGN_RATE_FLAG,
            "duplicate_rate_flag": DUPLICATE_RATE_FLAG,
        },
        "sources": reports,
        "unavailable": unavailable,
    }
    if len(frames) > 1:
        result["pooled"] = audit_pooled(frames)
    if "bipia" in reports and reports["bipia"].get("origin_confound"):
        result["bipia_origin_confound"] = reports["bipia"]["origin_confound"]
    return result


def print_summary(result: Dict[str, Any]) -> None:
    print(f"{'source':<12}{'n':>8}{'len_auc':>9}{'style_auc':>11}{'foreign':>9}  flags")
    for name, rep in result["sources"].items():
        la = "-" if rep["length_auc"] is None else f"{rep['length_auc']:.2f}"
        sa = "-" if rep["style_auc"] is None else f"{rep['style_auc']:.2f}"
        print(f"{name:<12}{rep['n']:>8}{la:>9}{sa:>11}{rep['language']['foreign_rate']:>9.2f}  {', '.join(rep['flags']) or 'ok'}")
    for name, why in result["unavailable"].items():
        print(f"{name:<12}  UNAVAILABLE: {why}")
    confound = result.get("bipia_origin_confound")
    if confound:
        print(f"bipia origin->label purity: {confound['origin_label_purity']} "
              f"(determines label: {confound['origin_determines_label']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", help="comma-separated source names (default: all that can load)")
    parser.add_argument("--bipia-jsonl", default=DEFAULT_BIPIA_JSONL)
    parser.add_argument("--csv", action="append", help="NAME=PATH to a csv with text,label_binary")
    parser.add_argument("--offline", action="store_true", help="skip Hugging Face sources")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    result = run(args)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print_summary(result)
    print(f"[INFO] Report written to {args.out}")


if __name__ == "__main__":
    main()
