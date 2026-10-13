"""
Metrics and calibration for the Layer 2 classifier. Pure numpy/sklearn: no torch needed, so it is
tested without a model and reused by evaluation scripts.

Reports include the numbers a firewall is judged on: recall on attacks, false positive rate on
normal text (what blocks real customers), and calibration (are 0.9 scores right 90% of the time?).
"""
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def attack_probability(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """P(attack) from two-class logits, optionally temperature-scaled."""
    return softmax(np.asarray(logits, dtype=float) / temperature)[:, 1]


def binary_metrics(y_true: Sequence[int], scores: Sequence[float], threshold: float = 0.5) -> Dict[str, Optional[float]]:
    """Precision, recall, F1, FPR, accuracy at `threshold`, plus AUC (None if one class only)."""
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)
    pred = (s >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (0.0 if tp + fp + fn else None)
    return {
        "n": int(len(y)), "positives": int(y.sum()), "threshold": float(threshold),
        "precision": _r(precision), "recall": _r(recall), "f1": _r(f1),
        "fpr": _r(fp / (fp + tn)) if fp + tn else None,
        "accuracy": _r((tp + tn) / max(len(y), 1)),
        "auc": _r(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else None,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def _r(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 4)


def best_threshold(y_true: Sequence[int], scores: Sequence[float], max_fpr: Optional[float] = None) -> float:
    """
    Threshold with the best F1 on the given (validation) data. With `max_fpr`, only thresholds whose
    false positive rate stays under that cap are considered: blocking customers is the costlier error.
    """
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)
    candidates = np.unique(np.round(s, 4))
    best, best_f1 = 0.5, -1.0
    for t in candidates:
        m = binary_metrics(y, s, float(t))
        if max_fpr is not None and m["fpr"] is not None and m["fpr"] > max_fpr:
            continue
        if (m["f1"] or 0.0) > best_f1:
            best, best_f1 = float(t), m["f1"] or 0.0
    return best


def group_metrics(rows: Iterable[Dict], key: str, y_key: str = "label", score_key: str = "score",
                  threshold: float = 0.5) -> Dict[str, Dict]:
    """Metrics per value of `key` (for example lang, source, style). Groups with one class still report counts."""
    groups: Dict[str, List[Dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key, "")), []).append(row)
    return {name: binary_metrics([r[y_key] for r in members], [r[score_key] for r in members], threshold)
            for name, members in sorted(groups.items())}


# ----------------------------- calibration -----------------------------
def expected_calibration_error(y_true: Sequence[int], scores: Sequence[float], bins: int = 10) -> float:
    """Average gap between confidence and accuracy over equal-width score bins."""
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(scores, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (s >= lo) & ((s < hi) if hi < 1.0 else (s <= hi))
        if mask.any():
            ece += mask.mean() * abs(y[mask].mean() - s[mask].mean())
    return float(ece)


def negative_log_likelihood(logits: np.ndarray, labels: Sequence[int], temperature: float) -> float:
    probs = softmax(np.asarray(logits, dtype=float) / temperature)
    picked = probs[np.arange(len(labels)), np.asarray(labels, dtype=int)]
    return float(-np.log(np.clip(picked, 1e-12, 1.0)).mean())


def fit_temperature(logits: np.ndarray, labels: Sequence[int]) -> float:
    """
    Temperature T > 0 that minimises validation NLL (probabilities = softmax(logits / T)).
    T > 1 softens an overconfident model, T < 1 sharpens an underconfident one. Does not change
    which side of 0.5 a prediction falls on, so accuracy is untouched; only the scores move.
    A coarse grid then a fine grid: simple, deterministic, and has no optimiser to fail on.
    """
    logits = np.asarray(logits, dtype=float)
    coarse = np.exp(np.linspace(np.log(0.05), np.log(20.0), 200))
    best = min(coarse, key=lambda t: negative_log_likelihood(logits, labels, float(t)))
    fine = np.linspace(best * 0.9, best * 1.1, 101)
    return float(min(fine, key=lambda t: negative_log_likelihood(logits, labels, float(t))))


def calibration_report(logits: np.ndarray, labels: Sequence[int]) -> Dict[str, float]:
    """Before/after numbers for the model card: temperature, NLL and ECE with and without scaling."""
    temperature = fit_temperature(logits, labels)
    before = attack_probability(logits, 1.0)
    after = attack_probability(logits, temperature)
    return {
        "temperature": round(temperature, 4),
        "nll_before": round(negative_log_likelihood(logits, labels, 1.0), 4),
        "nll_after": round(negative_log_likelihood(logits, labels, temperature), 4),
        "ece_before": round(expected_calibration_error(labels, before), 4),
        "ece_after": round(expected_calibration_error(labels, after), 4),
    }
