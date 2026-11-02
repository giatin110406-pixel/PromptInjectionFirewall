"""
Train XGBoost classifier on extracted features from mixed benchmark (International + Vietnamese).
Saves model artifact to models/layer2_xgboost/model.pkl.
Outputs overall and per-language evaluation metrics (accuracy, precision, recall, f1, ROC-AUC).
"""
import os
import sys
import joblib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, accuracy_score, precision_score, recall_score, f1_score
from models.layer2_xgboost.features import FEATURE_NAMES

FEATURES_PATH = os.path.join(BASE_DIR, "data", "processed", "features.csv")
MODEL_OUT_PATH = os.path.join(BASE_DIR, "models", "layer2_xgboost", "model.pkl")


def compute_metrics(y_true, y_pred, y_proba):
    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    try:
        auc = roc_auc_score(y_true, y_proba) if len(np.unique(y_true)) > 1 else 0.0
    except Exception:
        auc = 0.0
    return {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "roc_auc": auc,
    }


def train_model():
    if not os.path.exists(FEATURES_PATH):
        raise FileNotFoundError(f"Feature dataset not found at {FEATURES_PATH}. Run build_feature_dataset.py first.")

    df = pd.read_csv(FEATURES_PATH)
    X = df[FEATURE_NAMES]
    y = df["label_binary"]
    languages = df.get("language", pd.Series(["unknown"] * len(df)))

    print(f"[INFO] Training set size: {len(df)} samples across {len(FEATURE_NAMES)} features.")
    print("Class breakdown:\n", y.value_counts().to_string())
    if "language" in df.columns:
        print("Language breakdown:\n", df["language"].value_counts().to_string())

    # Stratified split
    indices = np.arange(len(df))
    train_idx, test_idx = train_test_split(
        indices, test_size=0.2, stratify=y, random_state=42
    )

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    lang_test = languages.iloc[test_idx]

    # Train with XGBoost or GradientBoosting
    try:
        import xgboost as xgb
        print("[INFO] Training with XGBoost Classifier...")
        clf = xgb.XGBClassifier(
            n_estimators=180,
            max_depth=5,
            learning_rate=0.06,
            subsample=0.85,
            colsample_bytree=0.85,
            eval_metric="logloss",
            random_state=42
        )
    except Exception as e:
        print(f"[WARN] XGBoost unavailable ({e}), using sklearn GradientBoostingClassifier fallback...")
        from sklearn.ensemble import GradientBoostingClassifier
        clf = GradientBoostingClassifier(
            n_estimators=180,
            max_depth=5,
            learning_rate=0.06,
            random_state=42
        )

    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    overall_metrics = compute_metrics(y_test, y_pred, y_proba)

    print("\n================ LAYER 2 MODEL OVERALL EVALUATION ================")
    print(f"Accuracy : {overall_metrics['accuracy'] * 100:.2f}%")
    print(f"Precision: {overall_metrics['precision'] * 100:.2f}%")
    print(f"Recall   : {overall_metrics['recall'] * 100:.2f}%")
    print(f"F1-Score : {overall_metrics['f1'] * 100:.2f}%")
    print(f"ROC-AUC  : {overall_metrics['roc_auc']:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["SAFE", "MALICIOUS"], digits=4))
    print("==================================================================")

    # Per-language evaluation
    print("\n================ PER-LANGUAGE EVALUATION METRICS ================")
    for lang in sorted(lang_test.unique()):
        mask = (lang_test == lang).values
        if sum(mask) == 0:
            continue
        y_test_lang = y_test.iloc[mask]
        y_pred_lang = y_pred[mask]
        y_proba_lang = y_proba[mask]
        m = compute_metrics(y_test_lang, y_pred_lang, y_proba_lang)
        print(f"[{lang.upper()}] (n={sum(mask)}) "
              f"Acc: {m['accuracy']*100:.2f}% | "
              f"Prec: {m['precision']*100:.2f}% | "
              f"Rec: {m['recall']*100:.2f}% | "
              f"F1: {m['f1']*100:.2f}% | "
              f"AUC: {m['roc_auc']:.4f}")
    print("=================================================================")

    assert overall_metrics["roc_auc"] >= 0.75, (
        f"Model AUC {overall_metrics['roc_auc']:.4f} is below acceptance criteria threshold (0.75)"
    )

    os.makedirs(os.path.dirname(MODEL_OUT_PATH), exist_ok=True)
    joblib.dump(clf, MODEL_OUT_PATH)
    print(f"[SUCCESS] Model saved to {MODEL_OUT_PATH}")
    return clf


if __name__ == "__main__":
    train_model()
