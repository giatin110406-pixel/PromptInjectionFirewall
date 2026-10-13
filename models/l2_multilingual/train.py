"""
Train the Layer 2 multilingual classifier (mDeBERTa-v3 by default) on chunk-level examples.

Runs on a Colab GPU (also locally). Reads data/processed/dataset_v2_{train,validation,test}.csv, cuts each
text into windows with `chunking.py`, trains, fits a temperature on the validation windows, and writes
everything the project needs into --out:

    <out>/checkpoint/        model + tokenizer (what firewall/classifier.py will load)
    <out>/temperature.json   calibration (temperature, NLL and ECE before/after)
    <out>/metrics.json       validation and test metrics, per language and per source
    <out>/train_log.json     loss per epoch, settings, dataset hashes, git-independent run info
    <out>/test_scores.csv    one row per test window (for error analysis and the thesis tables)

    python models/l2_multilingual/train.py --out models/l2_multilingual/artifacts
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from chunking import balance_chunks, build_examples  # noqa: E402
from metrics import (attack_probability, best_threshold, binary_metrics, calibration_report,  # noqa: E402
                     group_metrics)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data", "processed")


def file_hash(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:16]


def load_split(name: str, data_dir: str) -> list:
    frame = pd.read_csv(os.path.join(data_dir, f"dataset_v2_{name}.csv"), keep_default_na=False)
    return frame.to_dict("records")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="microsoft/mdeberta-v3-base")
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--out", default=os.path.join(HERE, "artifacts"))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-tokens", type=int, default=200, help="window size; 200 leaves room for special tokens")
    parser.add_argument("--stride", type=int, default=128)
    parser.add_argument("--safe-ratio", type=float, default=1.0, help="safe windows kept per attack window in TRAIN")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=0, help="debug: use only N documents per split")
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device={device} model={args.model}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)

    def offsets_fn(text: str):
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
        return [tuple(o) for o in encoded["offset_mapping"]]

    splits = {}
    for name in ("train", "validation", "test"):
        rows = load_split(name, args.data_dir)
        if args.limit:
            rows = rows[: args.limit]
        examples = build_examples(rows, offsets_fn, args.max_tokens, args.stride)
        if name == "train":
            examples = balance_chunks(examples, seed=args.seed, ratio=args.safe_ratio)
        splits[name] = examples
        labels = pd.Series([e["label"] for e in examples]).value_counts().to_dict()
        print(f"[INFO] {name}: {len(rows)} documents -> {len(examples)} windows {labels}")

    def encode(batch):
        return tokenizer([e["text"] for e in batch], truncation=True, max_length=args.max_tokens + 16,
                         padding=True, return_tensors="pt")

    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=2).float().to(device)  # fp32 master weights; autocast does the fp16
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    train = splits["train"]
    steps = max(1, (len(train) + args.batch_size - 1) // args.batch_size) * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.06 * steps), steps)
    use_amp = device == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    @torch.no_grad()
    def predict(examples, batch_size=64):
        model.eval()
        order = sorted(range(len(examples)), key=lambda i: len(examples[i]["text"]))
        logits = np.zeros((len(examples), 2), dtype=np.float32)
        for i in range(0, len(order), batch_size):
            idx = order[i:i + batch_size]
            enc = {k: v.to(device) for k, v in encode([examples[j] for j in idx]).items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                out = model(**enc).logits
            logits[idx] = out.float().cpu().numpy()
        return logits

    log = {"args": vars(args), "epochs": [], "data_hash": {
        s: file_hash(os.path.join(args.data_dir, f"dataset_v2_{s}.csv")) for s in ("train", "validation", "test")}}
    best_loss, best_state = float("inf"), None
    started = time.time()
    for epoch in range(args.epochs):
        model.train()
        random.shuffle(train)
        total = 0.0
        for i in range(0, len(train), args.batch_size):
            batch = train[i:i + args.batch_size]
            enc = {k: v.to(device) for k, v in encode(batch).items()}
            labels = torch.tensor([e["label"] for e in batch], device=device)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                loss = torch.nn.functional.cross_entropy(model(**enc).logits.float(), labels)
            optimizer.zero_grad()
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer); scaler.update(); scheduler.step()
            total += float(loss) * len(batch)
        val_logits = predict(splits["validation"])
        val_labels = [e["label"] for e in splits["validation"]]
        val_nll = calibration_report(val_logits, val_labels)["nll_before"]
        val_f1 = binary_metrics(val_labels, attack_probability(val_logits), 0.5)
        log["epochs"].append({"epoch": epoch + 1, "train_loss": round(total / len(train), 4),
                              "val_nll": val_nll, "val": val_f1, "minutes": round((time.time() - started) / 60, 1)})
        print(f"[INFO] epoch {epoch + 1}: train_loss={log['epochs'][-1]['train_loss']} val_nll={val_nll} val={val_f1}")
        if val_nll < best_loss:
            best_loss = val_nll
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    model.load_state_dict(best_state)
    val_logits = predict(splits["validation"])
    val_labels = [e["label"] for e in splits["validation"]]
    calibration = calibration_report(val_logits, val_labels)
    temperature = calibration["temperature"]
    val_scores = attack_probability(val_logits, temperature)
    threshold = best_threshold(val_labels, val_scores, max_fpr=0.01)

    test = splits["test"]
    test_logits = predict(test)
    test_scores = attack_probability(test_logits, temperature)
    test_labels = [e["label"] for e in test]
    rows = [dict(e, score=float(s)) for e, s in zip(test, test_scores)]
    metrics = {
        "threshold_fpr1pct_on_validation": threshold,
        "validation": binary_metrics(val_labels, val_scores, threshold),
        "test": binary_metrics(test_labels, test_scores, threshold),
        "test_by_lang": group_metrics(rows, "lang", threshold=threshold),
        "test_by_source": group_metrics(rows, "source", threshold=threshold),
        "calibration": calibration,
    }

    os.makedirs(args.out, exist_ok=True)
    ckpt = os.path.join(args.out, "checkpoint")
    model.save_pretrained(ckpt)
    tokenizer.save_pretrained(ckpt)
    with open(os.path.join(args.out, "temperature.json"), "w", encoding="utf-8") as h:
        json.dump({"temperature": temperature, "threshold": threshold, "max_tokens": args.max_tokens,
                   "stride": args.stride, "base_model": args.model}, h, indent=2)
    with open(os.path.join(args.out, "metrics.json"), "w", encoding="utf-8") as h:
        json.dump(metrics, h, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out, "train_log.json"), "w", encoding="utf-8") as h:
        json.dump(log, h, indent=2, ensure_ascii=False)
    pd.DataFrame(rows).drop(columns=["text"]).to_csv(os.path.join(args.out, "test_scores.csv"), index=False)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"[INFO] wrote {args.out}")


if __name__ == "__main__":
    main()
