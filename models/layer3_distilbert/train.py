"""Fine-tune DistilBERT on the normalized Layer 3 prompt dataset."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

DATA_PATH = os.path.join(BASE_DIR, "data", "processed", "ground_truth_layer3.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "models", "layer3_distilbert", "checkpoint")


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "precision": precision_score(labels, predictions, zero_division=0),
        "recall": recall_score(labels, predictions, zero_division=0),
        "f1": f1_score(labels, predictions, zero_division=0),
    }


def train_model(epochs: int = 3, batch_size: int = 16) -> None:
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Layer 3 dataset not found: {DATA_PATH}. Run prepare_real_datasets.py first.")

    from datasets import Dataset
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding,
                              Trainer, TrainingArguments)

    frame = pd.read_csv(DATA_PATH)[["text", "label_binary"]].dropna()
    if frame["label_binary"].nunique() < 2:
        raise ValueError("Layer 3 dataset must contain both label_binary=0 and label_binary=1.")
    train_frame, eval_frame = train_test_split(
        frame, test_size=0.2, stratify=frame["label_binary"], random_state=42
    )
    train_dataset = Dataset.from_pandas(train_frame.rename(columns={"label_binary": "labels"}), preserve_index=False)
    eval_dataset = Dataset.from_pandas(eval_frame.rename(columns={"label_binary": "labels"}), preserve_index=False)

    tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=256)

    train_dataset = train_dataset.map(tokenize, batched=True)
    eval_dataset = eval_dataset.map(tokenize, batched=True)
    model = AutoModelForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=2)

    common_args = dict(
        output_dir=OUTPUT_DIR,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=2e-5,
        weight_decay=0.01,
        logging_steps=25,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        report_to=[],
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
    trainer.train()
    metrics = trainer.evaluate()
    print(f"[INFO] Layer 3 evaluation: {metrics}")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"[SUCCESS] DistilBERT checkpoint saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    train_model()