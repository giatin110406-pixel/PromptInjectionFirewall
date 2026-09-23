"""
Extract feature matrix for all samples in ground_truth.csv.
Output: data/processed/features.csv
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd
from models.layer2_xgboost.features import extract_features, FEATURE_NAMES

GROUND_TRUTH_PATH = os.path.join(BASE_DIR, "data", "processed", "ground_truth.csv")
OUTPUT_FEATURES_PATH = os.path.join(BASE_DIR, "data", "processed", "features.csv")

def build_feature_dataset():
    if not os.path.exists(GROUND_TRUTH_PATH):
        raise FileNotFoundError(f"Ground truth not found at {GROUND_TRUTH_PATH}. Run data pipeline first.")

    df = pd.read_csv(GROUND_TRUTH_PATH)
    print(f"[INFO] Extracting features for {len(df)} samples...")

    feature_rows = []
    for idx, row in df.iterrows():
        text = str(row["text"])
        feats = extract_features(text)
        feats["label_binary"] = int(row["label_binary"])
        feats["label"] = str(row["label"])
        feature_rows.append(feats)

    features_df = pd.DataFrame(feature_rows)
    
    # Validation checks
    assert len(features_df) == len(df), "Row count mismatch"
    for col in FEATURE_NAMES:
        assert not features_df[col].isna().any(), f"NaN values detected in feature column {col}"

    os.makedirs(os.path.dirname(OUTPUT_FEATURES_PATH), exist_ok=True)
    features_df.to_csv(OUTPUT_FEATURES_PATH, index=False)
    print(f"[SUCCESS] Features dataset saved to {OUTPUT_FEATURES_PATH}")
    print(f"Shape: {features_df.shape} ({len(FEATURE_NAMES)} features + labels)")

if __name__ == "__main__":
    build_feature_dataset()
