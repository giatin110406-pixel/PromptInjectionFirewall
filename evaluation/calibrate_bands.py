"""
Choose the three numbers of the orchestrator that depend on the Layer 2 score distribution, for the model in
models/l2_multilingual/artifacts (or --artifacts), using ONLY dev data: the validation split of the dataset the model was
trained on, and the dev halves of tmdeptrai external and vi_test_v1. No test set and no public set is used.

    python evaluation/calibrate_bands.py --data-dir data/processed_public

  escalate_high      lowest score from which the blocks are reliable: among texts scoring at or above it, at most MAX_SAFE_SHARE
                     (1%) are safe. Blocks between the threshold and this value go to the judge or to REVIEW (consensus policy).
                     Also used as soft_block_below (a lone, unconfirmed block under this score is held, not blocked).
  escalate_low       the allow-side band [escalate_low, threshold): the lowest score (grid of 0.05) such that the whole band holds
                     at least MIN_ATTACK_TO_SAFE times as many attacks as safe texts, so the judge is not flooded with safe ones.
The old model used 0.30 / 0.98 / 0.98 (PrepareForBCTĐ2/04, 10, 13). Output: evaluation/results/band_calibration.json.
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

MAX_SAFE_SHARE = 0.011   # 1% plus rounding: the old model's cut (0.98) was chosen the same way
MIN_ATTACK_TO_SAFE = 2.0
OUT = os.path.join(BASE_DIR, "evaluation", "results", "band_calibration.json")
CACHE = os.path.join(BASE_DIR, "evaluation", "results", "band_calibration_scores.csv")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.path.join(BASE_DIR, "data", "processed_public"))
    parser.add_argument("--artifacts", default=os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts"))
    parser.add_argument("--use-cache", action="store_true", help="reuse the scores of the previous run (same model)")
    args = parser.parse_args()
    eval_layer1.PROCESSED = os.path.abspath(args.data_dir)

    from firewall.classifier import MultilingualClassifier

    clf = MultilingualClassifier(artifacts_dir=args.artifacts)
    assert clf.model is not None, clf.error
    threshold = clf.threshold
    frames = [(name, eval_layer1.load_set(name)) for name in ("validation", "external_dev", "vi_dev")]
    if args.use_cache and os.path.exists(CACHE):
        data = pd.read_csv(CACHE)
    else:
        rows = []
        for name, frame in frames:
            for text, label in zip(frame["text"], frame["label_binary"]):
                rows.append({"set": name, "label": int(label), "score": max(clf.window_scores(str(text)))})
            print(f"[INFO] scored {name}: {len(frame)}", flush=True)
        data = pd.DataFrame(rows)
        data.to_csv(CACHE, index=False)
    score, label = data["score"].to_numpy(), data["label"].to_numpy()
    safe, attack = label == 0, label == 1

    # ---- block side
    grid = np.round(np.arange(threshold, 1.0, 0.005), 3)
    high = None
    table = []
    for g in grid:
        flagged = score >= g
        n = int(flagged.sum())
        share = float((flagged & safe).sum() / n) if n else 0.0
        table.append({"from": float(g), "flagged": n, "safe_share": round(share, 4)})
        if high is None and share <= MAX_SAFE_SHARE and n >= 50:
            high = float(g)
    high = high if high is not None else float(grid[-1])

    # ---- allow side
    low = threshold
    for g in np.round(np.arange(0.90, 0.04, -0.05), 2):
        in_band = (score >= g) & (score < threshold)
        a_n, s_n = int((in_band & attack).sum()), int((in_band & safe).sum())
        if a_n >= MIN_ATTACK_TO_SAFE * s_n and a_n > 0:    # keep scanning: a single safe text must not stop the search
            low = float(g)
    band = (score >= low) & (score < threshold)
    report = {
        "model": os.path.relpath(args.artifacts, BASE_DIR), "threshold": threshold, "dev_rows": {n: len(f) for n, f in frames},
        "rules": {"max_safe_share_above_high": MAX_SAFE_SHARE, "min_attack_to_safe_in_allow_band": MIN_ATTACK_TO_SAFE},
        "escalate_low": low, "escalate_high": high, "soft_block_below": high,
        "dev_counts": {"attacks": int(attack.sum()), "safe": int(safe.sum())},
        "allow_band": {"attacks_in_band": int((band & attack).sum()), "safe_in_band": int((band & safe).sum()),
                       "attacks_missed_below_threshold": int((attack & (score < threshold)).sum())},
        "block_band": {"attacks": int(((score >= threshold) & (score < high) & attack).sum()), "safe": int(((score >= threshold) & (score < high) & safe).sum()),
                       "attacks_at_or_above_high": int(((score >= high) & attack).sum()), "safe_at_or_above_high": int(((score >= high) & safe).sum())},
        "safe_share_by_score": table[::2],
    }
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "safe_share_by_score"}, indent=1))


if __name__ == "__main__":
    main()
