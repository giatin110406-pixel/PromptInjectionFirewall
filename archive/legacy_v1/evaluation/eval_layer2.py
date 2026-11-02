"""
Evaluation script comparing Baseline (Regex-only) vs Layer 1 + Layer 2 (Prefilter + XGBoost).
Outputs a comparison table and saves to evaluation/results/layer2_comparison.json.
"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd
from sklearn.metrics import precision_recall_fscore_support, accuracy_score
from firewall.baseline import RegexBaseline
from firewall.layer1 import Layer1Prefilter
from firewall.layer2 import Layer2Classifier

GROUND_TRUTH_PATH = os.path.join(BASE_DIR, "data", "processed", "ground_truth.csv")
OUTPUT_PATH = os.path.join(BASE_DIR, "evaluation", "results", "layer2_comparison.json")

def evaluate_pipeline():
    if not os.path.exists(GROUND_TRUTH_PATH):
        raise FileNotFoundError(f"Dataset missing: {GROUND_TRUTH_PATH}")

    df = pd.read_csv(GROUND_TRUTH_PATH)
    y_true = df["label_binary"].values

    baseline = RegexBaseline()
    layer1 = Layer1Prefilter()
    layer2 = Layer2Classifier()

    baseline_preds = []
    l1_l2_preds = []
    l1_stops = 0
    l2_stops = 0

    print(f"[INFO] Evaluating {len(df)} samples across Baseline vs Layer 1 + Layer 2...")
    for text in df["text"].astype(str):
        # Baseline
        r_base = baseline.predict(text)
        baseline_preds.append(1 if r_base["is_attack"] else 0)

        # Layer 1 + Layer 2 pipeline
        r1 = layer1.check(text)
        if r1["decision"] == "BLOCK":
            l1_l2_preds.append(1)
            l1_stops += 1
        elif r1["decision"] == "PASS" and r1.get("confidence", 0.0) < 0.25:
            l1_l2_preds.append(0)
            l1_stops += 1
        else:
            r2 = layer2.check(text, top_similarity=r1.get("confidence", 0.0))
            pred = 1 if r2["decision"] in ["BLOCK", "ESCALATE"] else 0
            l1_l2_preds.append(pred)
            l2_stops += 1

    # Metrics
    base_acc = accuracy_score(y_true, baseline_preds)
    base_p, base_r, base_f1, _ = precision_recall_fscore_support(y_true, baseline_preds, average="binary", zero_division=0)

    l2_acc = accuracy_score(y_true, l1_l2_preds)
    l2_p, l2_r, l2_f1, _ = precision_recall_fscore_support(y_true, l1_l2_preds, average="binary", zero_division=0)

    comparison = {
        "dataset_size": len(df),
        "baseline_regex": {
            "accuracy": round(float(base_acc), 4),
            "precision": round(float(base_p), 4),
            "recall": round(float(base_r), 4),
            "f1_score": round(float(base_f1), 4),
        },
        "layer1_layer2_combined": {
            "accuracy": round(float(l2_acc), 4),
            "precision": round(float(l2_p), 4),
            "recall": round(float(l2_r), 4),
            "f1_score": round(float(l2_f1), 4),
            "layer1_stopped_count": l1_stops,
            "layer2_handled_count": l2_stops,
        },
        "improvements": {
            "accuracy_delta": round(float(l2_acc - base_acc), 4),
            "recall_delta": round(float(l2_r - base_r), 4),
            "f1_delta": round(float(l2_f1 - base_f1), 4),
        }
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)

    print("\n" + "=" * 65)
    print(f"{'METRIC':<18} | {'BASELINE (REGEX)':<18} | {'LAYER 1 + LAYER 2':<18} | {'IMPROVEMENT':<10}")
    print("-" * 65)
    print(f"{'Accuracy':<18} | {base_acc*100:>17.2f}% | {l2_acc*100:>17.2f}% | {+(l2_acc - base_acc)*100:>+9.2f}%")
    print(f"{'Precision':<18} | {base_p*100:>17.2f}% | {l2_p*100:>17.2f}% | {+(l2_p - base_p)*100:>+9.2f}%")
    print(f"{'Recall':<18} | {base_r*100:>17.2f}% | {l2_r*100:>17.2f}% | {+(l2_r - base_r)*100:>+9.2f}%")
    print(f"{'F1-Score':<18} | {base_f1*100:>17.2f}% | {l2_f1*100:>17.2f}% | {+(l2_f1 - base_f1)*100:>+9.2f}%")
    print("=" * 65)
    print(f"Layer distribution: {l1_stops} resolved at L1, {l2_stops} escalated to L2.")
    print(f"[INFO] Comparison saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    evaluate_pipeline()
