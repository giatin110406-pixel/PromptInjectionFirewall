import numpy as np
import pytest

from models.l2_multilingual import metrics as m


def test_binary_metrics_known_values():
    y = [1, 1, 1, 0, 0, 0, 0, 0]
    s = [0.9, 0.8, 0.3, 0.7, 0.2, 0.1, 0.05, 0.4]
    out = m.binary_metrics(y, s, 0.5)
    assert (out["tp"], out["fp"], out["fn"], out["tn"]) == (2, 1, 1, 4)
    assert out["precision"] == pytest.approx(2 / 3, abs=1e-3) and out["recall"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["fpr"] == pytest.approx(1 / 5, abs=1e-3) and out["accuracy"] == pytest.approx(6 / 8, abs=1e-3)
    assert out["auc"] is not None and 0.5 < out["auc"] < 1


def test_binary_metrics_handles_a_single_class_without_crashing():
    only_safe = m.binary_metrics([0, 0, 0], [0.1, 0.2, 0.9], 0.5)
    assert only_safe["auc"] is None and only_safe["recall"] is None and only_safe["fpr"] == pytest.approx(1 / 3, abs=1e-3)
    only_attack = m.binary_metrics([1, 1], [0.9, 0.2], 0.5)
    assert only_attack["fpr"] is None and only_attack["recall"] == 0.5


def test_perfect_and_worst_classifiers():
    perfect = m.binary_metrics([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert perfect["f1"] == 1.0 and perfect["fpr"] == 0.0 and perfect["auc"] == 1.0
    worst = m.binary_metrics([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1])
    assert worst["f1"] == 0.0 and worst["auc"] == 0.0


def test_best_threshold_and_the_false_positive_cap():
    y = [0] * 50 + [1] * 50
    rng = np.random.default_rng(0)
    s = np.concatenate([rng.beta(2, 5, 50), rng.beta(5, 2, 50)])
    free = m.best_threshold(y, s)
    capped = m.best_threshold(y, s, max_fpr=0.02)
    assert m.binary_metrics(y, s, capped)["fpr"] <= 0.02
    assert capped >= free  # a stricter cap can only raise the bar


def test_group_metrics_splits_by_key():
    rows = [{"label": 0, "score": 0.1, "lang": "vi"}, {"label": 1, "score": 0.9, "lang": "vi"},
            {"label": 0, "score": 0.8, "lang": "en"}, {"label": 1, "score": 0.9, "lang": "en"}]
    groups = m.group_metrics(rows, "lang")
    assert groups["vi"]["f1"] == 1.0 and groups["en"]["fpr"] == 1.0 and set(groups) == {"vi", "en"}


# ----------------------------- calibration -----------------------------
def _logits_with_scale(scale, n=4000, seed=0):
    """Two-class logits whose true confidence is 1/(1+e^-z) but which the model reports scaled by `scale`."""
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 2.0, n)
    labels = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    return np.stack([np.zeros(n), z * scale], axis=1), labels


def test_temperature_recovers_an_overconfident_model():
    logits, labels = _logits_with_scale(3.0)
    t = m.fit_temperature(logits, labels)
    assert t == pytest.approx(3.0, rel=0.15)


def test_temperature_recovers_an_underconfident_model():
    logits, labels = _logits_with_scale(0.4)
    assert m.fit_temperature(logits, labels) == pytest.approx(0.4, rel=0.15)


def test_calibration_improves_nll_and_ece_and_keeps_predictions_the_same_side_of_half():
    logits, labels = _logits_with_scale(3.0)
    report = m.calibration_report(logits, labels)
    assert report["nll_after"] < report["nll_before"] and report["ece_after"] < report["ece_before"]
    before = m.attack_probability(logits, 1.0) >= 0.5
    after = m.attack_probability(logits, report["temperature"]) >= 0.5
    assert (before == after).all()


def test_ece_is_zero_for_perfectly_calibrated_and_large_for_confidently_wrong():
    assert m.expected_calibration_error([0, 1], [0.0, 1.0]) == 0.0
    assert m.expected_calibration_error([1, 1, 1, 1], [0.0, 0.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_softmax_is_stable_for_huge_logits():
    out = m.softmax(np.array([[1000.0, 0.0], [0.0, 1000.0]]))
    assert np.allclose(out, [[1, 0], [0, 1]]) and not np.isnan(out).any()
