"""
Evaluate Regex Baseline Classifier on the Ground Truth Dataset.
Saves metrics to evaluation/results/baseline_metrics.json
"""
import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd
from sklearn.metrics import classification_report, precision_recall_fscore_support, accuracy_score
from firewall.baseline import RegexBaseline

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "processed", "ground_truth.csv")
OUTPUT_METRICS_PATH = os.path.join(BASE_DIR, "evaluation", "results", "baseline_metrics.json")

def evaluate_baseline():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Ground truth dataset not found at {DATA_PATH}. Run data pipeline scripts first.")

    df = pd.read_csv(DATA_PATH)
    print(f"[INFO] Loaded ground truth dataset with {len(df)} samples.")
    print("Class breakdown:\n", df["label"].value_counts())

    baseline = RegexBaseline()
    
    predictions = []
    matches = []
    
    for text in df["text"].astype(str):
        res = baseline.predict(text)
        predictions.append(1 if res["is_attack"] else 0)
        matches.append(res["matched_pattern"])

    y_true = df["label_binary"].values
    y_pred = predictions

    precision, recall, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    acc = accuracy_score(y_true, y_pred)

    metrics = {
        "model": "RegexBaseline",
        "dataset_size": len(df),
        "accuracy": round(float(acc), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1_score": round(float(f1), 4),
        "classification_report": classification_report(y_true, y_pred, target_names=["SAFE", "MALICIOUS"], output_dict=True, zero_division=0)
    }

    os.makedirs(os.path.dirname(OUTPUT_METRICS_PATH), exist_ok=True)
    with open(OUTPUT_METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print("\n================ BASELINE EVALUATION METRICS ================")
    print(f"Accuracy : {acc * 100:.2f}%")
    print(f"Precision: {precision * 100:.2f}%")
    print(f"Recall   : {recall * 100:.2f}%")
    print(f"F1-Score : {f1 * 100:.2f}%")
    print("=============================================================")
    print(f"[INFO] Saved metrics to {OUTPUT_METRICS_PATH}")

if __name__ == "__main__":
    evaluate_baseline()
