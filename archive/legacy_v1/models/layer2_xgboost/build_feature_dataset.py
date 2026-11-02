"""
Extract feature matrix for all samples in ground_truth_mixed.csv / ground_truth.csv.
Output: data/processed/features.csv
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd
from models.layer2_xgboost.features import extract_features, FEATURE_NAMES

PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
GROUND_TRUTH_MIXED_PATH = os.path.join(PROCESSED_DIR, "ground_truth_mixed.csv")
GROUND_TRUTH_PATH = os.path.join(PROCESSED_DIR, "ground_truth.csv")
OUTPUT_FEATURES_PATH = os.path.join(PROCESSED_DIR, "features.csv")


def build_feature_dataset(dataset_path: str = None):
    target_path = dataset_path
    if target_path is None:
        target_path = GROUND_TRUTH_MIXED_PATH if os.path.exists(GROUND_TRUTH_MIXED_PATH) else GROUND_TRUTH_PATH

    if not os.path.exists(target_path):
        raise FileNotFoundError(f"Ground truth dataset not found at {target_path}. Run data pipeline first.")

    df = pd.read_csv(target_path)
    print(f"[INFO] Extracting features for {len(df)} samples from {target_path}...")

    feature_rows = []
    for idx, row in df.iterrows():
        text = str(row["text"])
        feats = extract_features(text)
        feats["label_binary"] = int(row["label_binary"])
        feats["label"] = str(row.get("label", "MALICIOUS" if int(row["label_binary"]) == 1 else "SAFE"))
        feats["language"] = str(row.get("language", "unknown"))
        feats["dataset_source"] = str(row.get("dataset_source", "unknown"))
        feats["attack_type"] = str(row.get("attack_type", "unknown"))
        feature_rows.append(feats)

    features_df = pd.DataFrame(feature_rows)

    # Validation checks
    assert len(features_df) == len(df), "Row count mismatch"
    for col in FEATURE_NAMES:
        assert not features_df[col].isna().any(), f"NaN values detected in feature column {col}"

    os.makedirs(os.path.dirname(OUTPUT_FEATURES_PATH), exist_ok=True)
    features_df.to_csv(OUTPUT_FEATURES_PATH, index=False)
    print(f"[SUCCESS] Features dataset saved to {OUTPUT_FEATURES_PATH}")
    print(f"Shape: {features_df.shape} ({len(FEATURE_NAMES)} features + metadata)")
    if "language" in features_df.columns:
        print(f"Samples per language:\n{features_df['language'].value_counts().to_string()}")


if __name__ == "__main__":
    build_feature_dataset()
