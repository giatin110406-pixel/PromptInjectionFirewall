"""
Market guardrails as extra baselines (BCTĐ2: Baseline, group B4).

    python evaluation/eval_market_guardrails.py

Models (public, from Hugging Face; the model cache is kept on drive D: because drive C: is nearly full):
  G1  protectai/deberta-v3-base-prompt-injection-v2  (Apache-2.0, not gated). Binary classifier SAFE / INJECTION.
  The model reads at most 512 tokens, so each text is cut into word windows of about 300 words (overlapping by 50) and the
  text is flagged when any window is flagged. This is the same rule the firewall uses for its own Layer 2 (max over windows).

Same sets, same labels and same metrics as evaluation/eval_baseline_v3.py. Output: evaluation/results/guardrails_market.json
(per-text scores are cached in evaluation/results/guardrails_rows/).

Not measured here: meta-llama/Llama-Prompt-Guard-2-86M (gated: needs an accepted licence on Hugging Face) and commercial APIs
(need keys). Their absence is stated in the report.
"""
import json
import os
import sys
import time

os.environ.setdefault("HF_HOME", "D:/hf_cache")          # drive C: is nearly full; the model is about 0.7 GB
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "evaluation"))

import eval_l1_compare as c1  # noqa: E402
from eval_layer1 import wilson  # noqa: E402

R = os.path.join(BASE_DIR, "evaluation", "results")
ROWS = os.path.join(R, "guardrails_rows")
OUT = os.path.join(R, "guardrails_market.json")
MODEL = "protectai/deberta-v3-base-prompt-injection-v2"
SETS = ["deepset", "grayswan_ipi", "holdout_tensortrust", "holdout_injecagent_base", "holdout_injecagent_enhanced", "holdout_dolly_instr",
        "holdout_dolly_doc", "holdout_xquad_q", "holdout_xquad_doc", "test", "external_test", "vi_test"]
WORDS, OVERLAP = 300, 50


def windows(text: str):
    words = str(text).split()
    if len(words) <= WORDS:
        return [" ".join(words) or " "]
    out, start = [], 0
    while True:
        out.append(" ".join(words[start:start + WORDS]))
        if start + WORDS >= len(words):
            return out
        start += WORDS - OVERLAP


def load_model():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()
    labels = {int(k): v.upper() for k, v in model.config.id2label.items()}
    attack_id = [k for k, v in labels.items() if "INJECTION" in v or "JAILBREAK" in v]
    return tok, model, labels, attack_id


def score_texts(texts, tok, model, attack_id):
    import torch

    pieces, owner = [], []
    for i, t in enumerate(texts):
        for w in windows(t):
            pieces.append(w)
            owner.append(i)
    scores = np.zeros(len(pieces), dtype=np.float32)
    with torch.no_grad():
        for s in range(0, len(pieces), 16):
            enc = tok(pieces[s:s + 16], truncation=True, max_length=512, padding=True, return_tensors="pt")
            probs = torch.softmax(model(**enc).logits, dim=-1)
            scores[s:s + 16] = probs[:, attack_id].sum(dim=-1).numpy()
    doc = np.zeros(len(texts), dtype=np.float32)
    for k, i in enumerate(owner):
        doc[i] = max(doc[i], scores[k])
    return doc


def rate(hits, n):
    return {"n": int(n), "hits": int(hits), "rate": round(hits / n, 4) if n else None, "ci95": wilson(int(hits), int(n))}


def main() -> None:
    tok, model, labels, attack_id = load_model()
    print("labels:", labels, "attack ids:", attack_id, flush=True)
    report = {"model": MODEL, "labels": labels, "rule": f"max over {WORDS}-word windows (overlap {OVERLAP}); flagged when the attack probability >= 0.5",
              "sets": {}}
    os.makedirs(ROWS, exist_ok=True)
    for name in SETS:
        frame = c1.load(name)
        y = frame["label_binary"].to_numpy().astype(int)
        path = os.path.join(ROWS, f"{name}.csv")
        if os.path.exists(path) and len(pd.read_csv(path)) == len(frame):
            score = pd.read_csv(path)["score"].to_numpy()
        else:
            started = time.time()
            score = score_texts([str(t) for t in frame["text"]], tok, model, attack_id)
            pd.DataFrame({"score": score}).to_csv(path, index=False)
            print(f"[{name}] {len(frame)} texts in {time.time() - started:.0f}s", flush=True)
        flag = score >= 0.5
        entry = {"n": int(len(frame)), "attacks_flagged": None, "safe_flagged": None}
        if (y == 1).any():
            entry["attacks_flagged"] = rate(int(flag[y == 1].sum()), int((y == 1).sum()))
        if (y == 0).any():
            entry["safe_flagged"] = rate(int(flag[y == 0].sum()), int((y == 0).sum()))
        if len(set(y.tolist())) == 2:
            from sklearn.metrics import roc_auc_score
            entry["auc"] = round(float(roc_auc_score(y, score)), 4)
        report["sets"][name] = entry
        a = entry["attacks_flagged"]["rate"] if entry["attacks_flagged"] else None
        s = entry["safe_flagged"]["rate"] if entry["safe_flagged"] else None
        print(f"{name:28s} attacks {a}  safe {s}  auc {entry.get('auc')}", flush=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
