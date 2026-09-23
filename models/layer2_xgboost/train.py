"""
Train XGBoost classifier on extracted features.
Saves model artifact to models/layer2_xgboost/model.pkl
Outputs classification report and ROC-AUC score.
"""
import os
import sys
import joblib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, accuracy_score
from models.layer2_xgboost.features import FEATURE_NAMES

FEATURES_PATH = os.path.join(BASE_DIR, "data", "processed", "features.csv")
MODEL_OUT_PATH = os.path.join(BASE_DIR, "models", "layer2_xgboost", "model.pkl")

def train_model():
    if not os.path.exists(FEATURES_PATH):
        raise FileNotFoundError(f"Feature dataset not found at {FEATURES_PATH}")

    df = pd.read_csv(FEATURES_PATH)
    X = df[FEATURE_NAMES]
    y = df["label_binary"]

    print(f"[INFO] Training set size: {len(df)} samples across {len(FEATURE_NAMES)} features.")
    print("Class breakdown:\n", y.value_counts())

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    # Train with XGBoost or GradientBoosting
    try:
        import xgboost as xgb
        print("[INFO] Training with XGBoost Classifier...")
        clf = xgb.XGBClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            random_state=42
        )
    except Exception as e:
        print(f"[WARN] XGBoost unavailable ({e}), using sklearn GradientBoostingClassifier fallback...")
        from sklearn.ensemble import GradientBoostingClassifier
        clf = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.08,
            random_state=42
        )

    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    auc = roc_auc_score(y_test, y_proba)
    acc = accuracy_score(y_test, y_pred)

    print("\n================ LAYER 2 MODEL EVALUATION ================")
    print(f"Accuracy : {acc * 100:.2f}%")
    print(f"ROC-AUC  : {auc:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["SAFE", "MALICIOUS"], digits=4))
    print("==========================================================")

    assert auc >= 0.75, f"Model AUC {auc:.4f} is below acceptance criteria threshold (0.75)"

    os.makedirs(os.path.dirname(MODEL_OUT_PATH), exist_ok=True)
    joblib.dump(clf, MODEL_OUT_PATH)
    print(f"[SUCCESS] Model saved to {MODEL_OUT_PATH}")

if __name__ == "__main__":
    train_model()
