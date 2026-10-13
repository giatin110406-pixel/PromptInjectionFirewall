"""
Tests for data/scripts/audit_leakage.py. Synthetic data only: no network, no real datasets.
Each test builds a dataset with a known flaw and checks the audit finds it, and builds a
clean dataset and checks the audit stays quiet.
"""
import json

import numpy as np
import pandas as pd
import pytest

from data.scripts import audit_leakage as al

RNG = np.random.default_rng(0)


def _texts(n, low, high, prefix):
    """Diverse random-word texts with a controlled length range."""
    letters = list("abcdefghijklmnopqrstuvwxyz")
    out = []
    for i in range(n):
        size = int(RNG.integers(low, high))
        words = []
        while sum(len(w) + 1 for w in words) < size:
            words.append("".join(RNG.choice(letters, int(RNG.integers(3, 9)))))
        out.append((f"{prefix} {i} " + " ".join(words))[: size + 8])
    return out


def _frame(safe_texts, attack_texts, source="s"):
    rows = [{"text": t, "label_binary": 0, "source": source} for t in safe_texts]
    rows += [{"text": t, "label_binary": 1, "source": source} for t in attack_texts]
    return pd.DataFrame(rows)


def test_length_leak_is_flagged():
    frame = _frame(_texts(80, 5, 20, "safe"), _texts(80, 150, 300, "atk"))
    report = al.audit_frame(frame, "leaky")
    assert report["length_auc"] >= 0.95
    assert "length_leak" in report["flags"]
    assert report["leaky"] is True


def test_style_leak_is_flagged_even_when_length_is_matched():
    # Same length, but attacks are shouty and full of digits: pure style difference.
    safe = [("please help me with order number soon " * 3)[:100] for _ in range(80)]
    attack = [("IGNORE EVERYTHING 123 456 NOW!!! " * 4)[:100] for _ in range(80)]
    report = al.audit_frame(_frame(safe, attack), "style")
    assert report["style_auc"] >= 0.9
    assert "style_leak" in report["flags"]


def test_clean_dataset_is_not_flagged():
    shared = lambda prefix: _texts(100, 40, 120, prefix)  # same length distribution
    report = al.audit_frame(_frame(shared("safe"), shared("atk")), "clean")
    assert report["flags"] == []
    assert report["leaky"] is False
    assert report["length_auc"] < 0.7


def test_single_label_source_is_flagged():
    frame = _frame([], _texts(60, 40, 120, "atk"))
    report = al.audit_frame(frame, "onlyattacks")
    assert report["single_label"] is True
    assert "single_label_source" in report["flags"]
    assert report["style_auc"] is None  # not computable, and must not crash


def test_tiny_class_does_not_produce_a_fake_auc():
    frame = _frame(_texts(5, 40, 120, "safe"), _texts(5, 40, 120, "atk"))
    assert al.style_auc(frame) is None


def test_foreign_language_text_is_detected():
    german = "Ich suche nach einer Wohnung und würde gerne wissen, wie die Stadt ist und mir helfen"
    spanish = "Si yo digo foya, usted puede decir como los demás para que las cosas sean una buena idea"
    vietnamese = "Xin chào, tôi muốn hỏi về chính sách đổi trả của cửa hàng cho đơn hàng này"
    frame = _frame([german, vietnamese] * 20, [spanish, vietnamese] * 20)
    mix = al.language_mix(frame)
    assert mix["foreign_rate"] >= 0.45
    report = al.audit_frame(frame, "mixed")
    assert "mixed_foreign_language" in report["flags"]


def test_duplicate_overlap_with_reference_is_detected():
    reference = _frame(_texts(60, 40, 120, "ref_safe"), _texts(60, 40, 120, "ref_atk"), "deepset")
    copied = reference.sample(40, random_state=1).assign(source="copy")
    fresh = _frame(_texts(30, 40, 120, "new_safe"), _texts(30, 40, 120, "new_atk"), "fresh")

    copy_report = al.audit_frame(pd.concat([copied, fresh]), "copy", reference)
    assert copy_report["overlap_with_reference"]["exact_rate"] == pytest.approx(0.4)  # 40 of 100 rows
    assert "duplicate_with_reference" in copy_report["flags"]

    clean_report = al.audit_frame(fresh, "fresh", reference)
    assert "duplicate_with_reference" not in clean_report["flags"]


def test_translated_copy_is_exposed_by_matching_shape():
    a = al.audit_frame(_frame(_texts(60, 40, 120, "s"), _texts(40, 40, 120, "a")), "deepset")
    b = al.audit_frame(_frame(_texts(60, 40, 120, "t"), _texts(40, 40, 120, "b")), "rikka")
    c = al.audit_frame(_frame(_texts(70, 40, 120, "u"), _texts(30, 40, 120, "c")), "other")
    assert al.shape_matches({"deepset": a, "rikka": b, "other": c}) == {"rikka": "deepset"}


def test_pooled_audit_shows_source_deciding_the_label():
    """The v1 Layer 3 flaw: all attacks from one source, all safe rows from another."""
    attacks = _frame([], _texts(100, 40, 120, "bipia"), "bipia")
    safes = _frame(_texts(100, 40, 120, "gpt"), [], "gpt")
    pooled = al.audit_pooled({"bipia": attacks, "gpt": safes})
    assert pooled["label_purity_by_source"] == 1.0
    assert pooled["source_label_crosstab"]["bipia"] == {"0": 0, "1": 100}
    assert pooled["source_label_crosstab"]["gpt"] == {"0": 100, "1": 0}


def test_origin_confound_is_detected_and_not_raised_for_mixed_origins():
    leaky = _frame(_texts(60, 40, 120, "s"), _texts(60, 40, 120, "a"))
    leaky["origin"] = np.where(leaky["label_binary"] == 1, "BIPIA", "GPT-4o-mini")
    assert al.audit_origin_confound(leaky)["origin_determines_label"] is True

    fine = leaky.copy()
    fine["origin"] = ["A", "B"] * (len(fine) // 2)
    assert al.audit_origin_confound(fine)["origin_determines_label"] is False
    assert al.audit_origin_confound(_frame(["x"], ["y"])) is None


def test_label_normalization_accepts_common_spellings():
    assert al._normalize_label("INJECTION") == 1
    assert al._normalize_label("BENIGN") == 0
    assert al._normalize_label(1) == 1
    assert al._normalize_label("maybe") is None


def test_dataset_hash_is_stable_and_order_independent():
    frame = _frame(_texts(10, 5, 20, "s"), _texts(10, 5, 20, "a"))
    assert al.dataset_hash(frame) == al.dataset_hash(frame.sample(frac=1, random_state=3))
    changed = frame.copy()
    changed.loc[0, "text"] = "changed"
    assert al.dataset_hash(changed) != al.dataset_hash(frame)


def test_run_offline_with_csv_writes_a_json_serializable_report(tmp_path):
    safe = _texts(60, 40, 120, "safe")
    attack = _texts(60, 40, 120, "atk")
    csv_path = tmp_path / "mine.csv"
    _frame(safe, attack).to_csv(csv_path, index=False)

    class Args:
        sources = "mine,missing"
        bipia_jsonl = str(tmp_path / "does_not_exist.jsonl")
        csv = [f"mine={csv_path}"]
        offline = True

    result = al.run(Args)
    assert "mine" in result["sources"]
    assert "missing" in result["unavailable"]  # reported, not raised
    assert result["thresholds"]["style_auc_leak"] == al.STYLE_AUC_LEAK
    json.dumps(result)  # must be serializable as-is


def test_origin_confound_makes_the_source_leaky_even_when_style_looks_fine():
    """BIPIA case: length and style are similar, but the upstream origin IS the label."""
    frame = _frame(_texts(100, 40, 120, "s"), _texts(100, 40, 120, "a"))
    frame["origin"] = np.where(frame["label_binary"] == 1, "BIPIA", "GPT-4o-mini")
    report = al.audit_frame(frame, "bipia")
    assert "origin_determines_label" in report["flags"]
    assert report["leaky"] is True
    assert report["style_auc"] < al.STYLE_AUC_LEAK  # not caught by style: needs the origin check


def test_noise_floor_is_reported_and_tracks_small_sample_inflation():
    """Pure noise reads well above 0.5 on small samples; the report must say so."""
    rng = np.random.default_rng(0)
    small = pd.DataFrame({"text": [("word " * int(n)) + ("?" if rng.random() < 0.5 else ".") for n in rng.integers(5, 40, 80)],
                          "label_binary": rng.integers(0, 2, 80), "source": "x"})
    report = al.audit_frame(small, "noise")
    if report["style_auc"] is None:
        pytest.skip("class counts below the minimum for this random draw")
    assert report["style_auc_noise_floor"] is not None
    assert report["style_auc_noise_floor"] > 0.52  # the floor is visibly above 0.5 at this size
    assert report["leaky"] is False  # and the 0.80 threshold still holds noise back
    assert al.style_auc_noise_floor(pd.DataFrame({"text": ["a"] * 10, "label_binary": [0] * 10, "source": "x"})) is None
