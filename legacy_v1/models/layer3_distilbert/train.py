"""
Fine-tune Deep Sequence Classifier (Multilingual Transformer / DistilBERT) on prompt safety dataset.

Supports:
- Multilingual backbones: 'distilbert-base-multilingual-cased', 'xlm-roberta-base', 'distilbert-base-uncased'
- Mixed and Two-Stage curriculum training:
  - Stage A: Initial training on international benchmark
  - Stage B: Specialized fine-tuning on Vietnamese and mixed attacks
- Per-language evaluation reporting (English, Vietnamese, Mixed).
"""
import argparse
import os
import sys
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split

PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
MIXED_DATA_PATH = os.path.join(PROCESSED_DIR, "ground_truth_layer3_mixed.csv")
FALLBACK_DATA_PATH = os.path.join(PROCESSED_DIR, "ground_truth_layer3.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "models", "layer3_distilbert", "checkpoint")

DEFAULT_MODEL_NAME = "distilbert-base-multilingual-cased"


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    probs = 1.0 / (1.0 + np.exp(-logits[:, 1])) if logits.shape[-1] == 2 else logits
    predictions = np.argmax(logits, axis=-1)
    metrics = {
        "accuracy": float(accuracy_score(labels, predictions)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
    }
    try:
        if len(np.unique(labels)) > 1:
            metrics["roc_auc"] = float(roc_auc_score(labels, probs))
    except Exception:
        pass
    return metrics


def evaluate_per_language(model, tokenizer, test_df: pd.DataFrame, device: str = "cpu") -> Dict[str, Any]:
    """Compute per-language accuracy and F1 on held-out test dataframe."""
    import torch

    results = {}
    if "language" not in test_df.columns or test_df.empty:
        return results

    model.eval()
    for lang in sorted(test_df["language"].unique()):
        sub = test_df[test_df["language"] == lang]
        if sub.empty or sub["label_binary"].nunique() < 1:
            continue

        inputs = tokenizer(
            sub["text"].tolist(),
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt"
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = model(**inputs).logits
            preds = torch.argmax(logits, dim=-1).cpu().numpy()

        y_true = sub["label_binary"].values
        results[lang] = {
            "samples": len(sub),
            "accuracy": float(accuracy_score(y_true, preds)),
            "precision": float(precision_score(y_true, preds, zero_division=0)),
            "recall": float(recall_score(y_true, preds, zero_division=0)),
            "f1": float(f1_score(y_true, preds, zero_division=0)),
        }
    return results


def train_model(
    model_name: str = DEFAULT_MODEL_NAME,
    dataset_path: Optional[str] = None,
    epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    strategy: str = "mixed",
    stage: str = "mixed",
) -> None:
    path = dataset_path or (MIXED_DATA_PATH if os.path.exists(MIXED_DATA_PATH) else FALLBACK_DATA_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Layer 3 dataset not found: {path}. Run prepare_real_datasets.py first.")

    df = pd.read_csv(path)
    if "label_binary" not in df.columns or df["label_binary"].nunique() < 2:
        raise ValueError("Layer 3 dataset must contain both safe and malicious labels.")

    if "language" not in df.columns:
        from data.scripts.vietnamese_norm import detect_language
        df["language"] = df["text"].apply(detect_language)

    print(f"[INFO] Layer 3 dataset loaded: {len(df)} samples from {path}")
    print(f"Languages: {df['language'].value_counts().to_dict()}")
    print(f"Labels: {df['label_binary'].value_counts().to_dict()}")

    # Filter subsets based on training stage
    if stage == "stage_a_intl":
        df = df[df["language"] == "en"].reset_index(drop=True)
        print(f"[INFO] Stage A: Filtered to {len(df)} international samples.")
    elif stage == "stage_b_vi":
        df = df[df["language"].isin(["vi", "mixed"])].reset_index(drop=True)
        print(f"[INFO] Stage B: Filtered to {len(df)} Vietnamese / mixed samples.")

    from datasets import Dataset
    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    train_frame, test_frame = train_test_split(
        df, test_size=0.2, stratify=df["label_binary"], random_state=42
    )

    train_dataset = Dataset.from_pandas(
        train_frame[["text", "label_binary"]].rename(columns={"label_binary": "labels"}),
        preserve_index=False,
    )
    eval_dataset = Dataset.from_pandas(
        test_frame[["text", "label_binary"]].rename(columns={"label_binary": "labels"}),
        preserve_index=False,
    )

    backbone_source = model_name
    if stage == "stage_b_vi" and model_name == DEFAULT_MODEL_NAME:
        if os.path.exists(os.path.join(OUTPUT_DIR, "model.safetensors")):
            print(f"[INFO] Stage B: Found previous checkpoint at {OUTPUT_DIR}. Continuing fine-tuning...")
            backbone_source = OUTPUT_DIR

    print(f"[INFO] Loading backbone: {backbone_source}...")
    tokenizer = AutoTokenizer.from_pretrained(backbone_source)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=256)

    train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])
    eval_dataset = eval_dataset.map(tokenize, batched=True, remove_columns=["text"])

    model = AutoModelForSequenceClassification.from_pretrained(backbone_source, num_labels=2)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    common_args = dict(
        output_dir=OUTPUT_DIR,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=0.01,
        logging_steps=20,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        report_to=[],
        dataloader_pin_memory=torch.cuda.is_available(),
    )
    try:
        training_args = TrainingArguments(eval_strategy="epoch", **common_args)
    except TypeError:
        training_args = TrainingArguments(evaluation_strategy="epoch", **common_args)

    trainer_kwargs = {
        "model": model,
        "args": training_args,
        "train_dataset": train_dataset,
        "eval_dataset": eval_dataset,
        "data_collator": DataCollatorWithPadding(tokenizer=tokenizer),
        "compute_metrics": compute_metrics,
    }
    try:
        trainer = Trainer(processing_class=tokenizer, **trainer_kwargs)
    except TypeError:
        trainer = Trainer(tokenizer=tokenizer, **trainer_kwargs)

    print(f"[INFO] Starting training with strategy={strategy}, stage={stage}...")
    trainer.train()

    eval_metrics = trainer.evaluate()
    print(f"\n================ LAYER 3 OVERALL EVALUATION ================")
    print(eval_metrics)
    print("============================================================")

    # Per-language evaluation
    per_lang = evaluate_per_language(model, tokenizer, test_frame, device=device)
    if per_lang:
        print("\n================ PER-LANGUAGE EVALUATION METRICS ================")
        for lang, m in per_lang.items():
            print(f"[{lang.upper()}] (n={m['samples']}) Acc: {m['accuracy']*100:.2f}% | "
                  f"Prec: {m['precision']*100:.2f}% | Rec: {m['recall']*100:.2f}% | F1: {m['f1']*100:.2f}%")
        print("=================================================================")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"[SUCCESS] Model checkpoint and tokenizer saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Layer 3 Deep Classifier")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="Hugging Face model backbone")
    parser.add_argument("--dataset", default=None, help="Path to Layer 3 CSV dataset")
    parser.add_argument("--epochs", type=int, default=3, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument("--strategy", choices=["mixed", "two_stage"], default="mixed", help="Training strategy")
    parser.add_argument("--stage", choices=["mixed", "stage_a_intl", "stage_b_vi"], default="mixed", help="Curriculum stage")
    args = parser.parse_args()

    train_model(
        model_name=args.model_name,
        dataset_path=args.dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        strategy=args.strategy,
        stage=args.stage,
    )