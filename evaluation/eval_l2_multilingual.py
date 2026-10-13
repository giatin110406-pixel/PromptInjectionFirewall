"""
Measure Layer 2 (mDeBERTa) per DOCUMENT, next to Layer 1, on text neither layer was tuned or trained on.

    python evaluation/eval_l2_multilingual.py

Protocol:
  - a document is cut into the same windows used in training (200 tokens, stride 128); it is flagged when ANY
    window scores >= the threshold stored with the checkpoint (temperature.json). That is how production scans
    untrusted documents, and it is stricter than the per-window numbers printed by train.py;
  - sets: dataset_v2 test, tmdeptrai external (dev and test halves), vi_test_v1 (dev and test halves).
    The two halves only matter for Layer 1, whose thresholds were tuned on the dev halves, so its dev numbers are
    optimistic. Layer 2 was tuned on dataset_v2 validation only, so all of these sets are unseen for it;
  - Layer 1 is the shipped layer (BLOCK only); "L1 or L2" blocks when either does;
  - 95% Wilson intervals: small sets give wide ones.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "models", "l2_multilingual"))
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

from chunking import token_windows  # noqa: E402
from eval_layer1 import load_set, wilson  # noqa: E402
from metrics import attack_probability  # noqa: E402

ARTIFACTS = os.path.join(BASE_DIR, "models", "l2_multilingual", "artifacts")
RESULTS = os.path.join(BASE_DIR, "evaluation", "results", "l2_eval.json")
SETS = ["test", "external_dev", "external_test", "vi_dev", "vi_test"]


def window_texts(text: str, tokenizer, max_tokens: int, stride: int):
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)
    offsets = encoded["offset_mapping"]
    pieces = []
    for a, b in token_windows(len(offsets), max_tokens, stride):
        piece = text[offsets[a][0]:offsets[b - 1][1]]
        if piece.strip():
            pieces.append(piece)
    return pieces or [text[:2000] or " "]


def score_documents(texts, model, tokenizer, cfg, device, batch=32):
    import torch

    pieces, owner = [], []
    for i, text in enumerate(texts):
        for piece in window_texts(str(text), tokenizer, cfg["max_tokens"], cfg["stride"]):
            pieces.append(piece)
            owner.append(i)
    order = sorted(range(len(pieces)), key=lambda k: len(pieces[k]))
    logits = np.zeros((len(pieces), 2), dtype=np.float32)
    started = time.time()
    with torch.no_grad():
        for s in range(0, len(order), batch):
            idx = order[s:s + batch]
            enc = tokenizer([pieces[k] for k in idx], truncation=True, max_length=cfg["max_tokens"] + 16,
                            padding=True, return_tensors="pt").to(device)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
                out = model(**enc).logits
            logits[idx] = out.float().cpu().numpy()
    scores = attack_probability(logits, cfg["temperature"])
    doc = np.zeros(len(texts))
    for k, i in enumerate(owner):
        doc[i] = max(doc[i], scores[k])
    return doc, len(pieces), time.time() - started


def rates(y, flagged):
    y, flagged = np.asarray(y), np.asarray(flagged)
    n_attack, n_safe = int((y == 1).sum()), int((y == 0).sum())
    tp, fp = int(((flagged == 1) & (y == 1)).sum()), int(((flagged == 1) & (y == 0)).sum())
    return {"n_attacks": n_attack, "n_safe": n_safe,
            "recall": round(tp / n_attack, 4) if n_attack else None, "recall_ci95": wilson(tp, n_attack),
            "fpr": round(fp / n_safe, 4) if n_safe else None, "fpr_ci95": wilson(fp, n_safe)}


def main() -> None:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from firewall.layer1 import Layer1Prefilter

    with open(os.path.join(ARTIFACTS, "temperature.json"), "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ckpt = os.path.join(ARTIFACTS, "checkpoint")
    tokenizer = AutoTokenizer.from_pretrained(ckpt)
    model = AutoModelForSequenceClassification.from_pretrained(ckpt).float().to(device).eval()
    layer1 = Layer1Prefilter()
    print(f"[INFO] device={device} threshold={cfg['threshold']} temperature={cfg['temperature']} l1_degraded={getattr(layer1, 'degraded', None)}")

    report = {"threshold": cfg["threshold"], "temperature": cfg["temperature"], "sets": {}}
    for name in SETS:
        frame = load_set(name)
        texts = frame["text"].tolist()
        y = frame["label_binary"].to_numpy()
        doc, n_windows, seconds = score_documents(texts, model, tokenizer, cfg, device)
        l2 = (doc >= cfg["threshold"]).astype(int)
        l1 = np.array([1 if layer1.check(t)["decision"] == "BLOCK" else 0 for t in texts])
        entry = {"n": len(frame), "windows": n_windows, "l2_seconds": round(seconds, 1),
                 "L1": rates(y, l1), "L2": rates(y, l2), "L1_or_L2": rates(y, np.maximum(l1, l2)),
                 "by_language": {}}
        for lang, g in frame.groupby("lang"):
            if lang:
                ix = g.index.to_numpy()
                entry["by_language"][lang] = {"L1": rates(y[ix], l1[ix]), "L2": rates(y[ix], l2[ix]),
                                              "L1_or_L2": rates(y[ix], np.maximum(l1, l2)[ix])}
        if "attack_type" in frame:
            atk = frame[frame["label_binary"] == 1]
            entry["recall_by_attack_type"] = {t: {"n": int(len(g)), "L1": round(float(l1[g.index].mean()), 3),
                                                  "L2": round(float(l2[g.index].mean()), 3),
                                                  "L1_or_L2": round(float(np.maximum(l1, l2)[g.index].mean()), 3)}
                                              for t, g in atk.groupby("attack_type") if t}
        wrong = frame.assign(l2=l2, score=doc.round(3))
        entry["l2_false_positives"] = wrong[(wrong.label_binary == 0) & (wrong.l2 == 1)][["text", "score"]].head(8).to_dict("records")
        entry["l2_misses"] = wrong[(wrong.label_binary == 1) & (wrong.l2 == 0)][["text", "score"]].head(8).to_dict("records")
        report["sets"][name] = entry
        print(f"[{name}] n={len(frame)} L1 r={entry['L1']['recall']} fpr={entry['L1']['fpr']} | "
              f"L2 r={entry['L2']['recall']} fpr={entry['L2']['fpr']} | L1+L2 r={entry['L1_or_L2']['recall']} fpr={entry['L1_or_L2']['fpr']}")

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print(f"[INFO] wrote {RESULTS}")


if __name__ == "__main__":
    main()
