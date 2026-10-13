"""Count what the Word report claims about datasets, directly from the files. Prints facts; judgement is done by the reader."""
import glob
import json
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def mb(path):
    return f"{os.path.getsize(path) / 1e6:.2f} MB ({os.path.getsize(path)} B)"


print("== dataset_v2 files")
frames = []
for s in ("train", "validation", "test"):
    p = f"data/processed/dataset_v2_{s}.csv"
    d = pd.read_csv(p, keep_default_na=False)
    frames.append(d.assign(split=s))
    print(s, len(d), mb(p), "mtime", os.path.getmtime(p))
data = pd.concat(frames)
print("total", len(data), "attack", int(data.label_binary.sum()), "benign", int((data.label_binary == 0).sum()))

print("== attack_type (attacks only) train / test")
a = data[data.label_binary == 1]
print(a.groupby(["attack_type", "split"]).size().unstack(fill_value=0).to_string())
print("== synthetic_kind by split (both labels)")
print(data.groupby(["synthetic_kind", "split"]).size().unstack(fill_value=0).to_string())
print("== is_synthetic")
print(data.is_synthetic.astype(str).value_counts().to_dict())
print("== is_synthetic by source")
print(data.groupby(["source", data.is_synthetic.astype(str)]).size().to_string())
print("== lang by split")
print(data.groupby(["lang", "split"]).size().unstack(fill_value=0).to_string())
print("== label balance per split x lang")
print(data.groupby(["split", "lang", "label_binary"]).size().unstack(fill_value=0).to_string())
print("== variants")
print(data.groupby("variant").size().sort_values(ascending=False).head(14).to_string())
print("== unique orig_id per split and overlap across splits")
ids = {s: set(data[data.split == s].orig_id) for s in ("train", "validation", "test")}
print({s: len(v) for s, v in ids.items()}, "train&val", len(ids["train"] & ids["validation"]), "train&test", len(ids["train"] & ids["test"]), "val&test", len(ids["validation"] & ids["test"]))
tid = {s: set(x for x in data[(data.split == s) & (data.template_id != "")].template_id) for s in ("train", "validation", "test")}
print("template ids", {s: len(v) for s, v in tid.items()}, "train&test", len(tid["train"] & tid["test"]), "train&val", len(tid["train"] & tid["validation"]))
n = lambda t: re.sub(r"\s+", " ", str(t).strip().lower())
tr, te, va = (set(map(n, data[data.split == s].text)) for s in ("train", "test", "validation"))
print("exact text overlap train&test", len(tr & te), "train&val", len(tr & va))
ins = {s: set(map(n, data[(data.split == s) & (data.insert_text != "")].insert_text)) for s in ("train", "validation", "test")}
print("shared insert_text train&test", len(ins["train"] & ins["test"]), "train&val", len(ins["train"] & ins["validation"]))
print("benign insert_text shared (benign-note bank):", len({n(t) for t in data[(data.label_binary == 0) & (data.insert_text != "")].insert_text}))

print("== L1 regex counts")
src = open("firewall/baseline.py", encoding="utf-8").read()
for name in ("DEFAULT_BASELINE_PATTERNS", "SOFT_BASELINE_PATTERNS", "ESCALATE_HINT_PATTERNS"):
    m = re.search(name + r"\s*=\s*\[(.*?)\n\]", src, re.S)
    print(name, "entries ~", len(re.findall(r'^\s*r?["\']', m.group(1), re.M)) if m else "not found")
l1 = open("firewall/layer1.py", encoding="utf-8").read()
print("extra patterns in layer1.py:", len(re.findall(r'^\s*r["\']', l1, re.M)))

print("== jailbreak_patterns.json")
jp = json.load(open("models/layer1_prefilter/jailbreak_patterns.json", encoding="utf-8"))
print(len(jp), mb("models/layer1_prefilter/jailbreak_patterns.json"))

print("== L1 index")
for f in ("vectors.npy", "entries.json", "meta.json", "thresholds.json"):
    print(f, mb(f"models/layer1_prefilter/index/{f}"))
meta = json.load(open("models/layer1_prefilter/index/meta.json", encoding="utf-8"))
print({k: v for k, v in meta.items() if k != "sources"})
print(json.load(open("models/layer1_prefilter/index/thresholds.json", encoding="utf-8")))

print("== eval sets and seeds")
for f in ("data/eval/vi_test_v1.csv", "data/eval/tmdeptrai_external_test.csv", "data/seeds/attack_bank.json", "data/seeds/benign_bank.json", "data/seeds/benign_support_actions.json"):
    print(f, mb(f))
print("== raw generated")
for f in sorted(glob.glob("data/raw/generated_vi/*.jsonl")):
    with open(f, encoding="utf-8") as h:
        print(os.path.basename(f), sum(1 for l in h if l.strip()), mb(f))
for f in sorted(glob.glob("data/raw/hard_cases/*.jsonl"))[:3]:
    pass
print("hard_cases dir", sum(os.path.getsize(f) for f in glob.glob("data/raw/hard_cases/*")) / 1e6, "MB;", "translation dir", sum(os.path.getsize(f) for f in glob.glob("data/raw/translation/*")) / 1e6, "MB;", "generated_vi dir", sum(os.path.getsize(f) for f in glob.glob("data/raw/generated_vi/*") if os.path.isfile(f)) / 1e6, "MB")
print("== dataset_for_huggingface.jsonl")
hp = "dataset_for_huggingface.jsonl"
if os.path.exists(hp):
    with open(hp, encoding="utf-8") as h:
        first = json.loads(h.readline()); count = 1 + sum(1 for _ in h)
    print(count, mb(hp), list(first.keys()))
else:
    print("not found at root")
print("== chroma")
print(mb("data/chroma_db/chroma.sqlite3"))
print("== L2 artifacts")
for f in ("checkpoint/model.safetensors", "checkpoint/tokenizer.json", "temperature.json", "metrics.json", "train_log.json", "test_scores.csv"):
    print(f, mb("models/l2_multilingual/artifacts/" + f))
print(open("models/l2_multilingual/artifacts/temperature.json", encoding="utf-8").read())
log = json.load(open("models/l2_multilingual/artifacts/train_log.json", encoding="utf-8"))
for e in log["epochs"]:
    v = e["val"]
    print("epoch", e["epoch"], e["train_loss"], e["val_nll"], "recall", v["recall"], "fpr", v["fpr"], e["minutes"])
m = json.load(open("models/l2_multilingual/artifacts/metrics.json", encoding="utf-8"))
for k in ("validation", "test"):
    x = m[k]; print(k, x["n"], x["precision"], x["recall"], x["f1"], x["fpr"], x["auc"], x["tp"], x["fp"], x["fn"], x["tn"])
for k, x in m["test_by_lang"].items():
    print("test", k, x["n"], x["precision"], x["recall"], x["f1"], x["fpr"], x["auc"], x["tp"], x["fp"], x["fn"], x["tn"])
print("calibration", m["calibration"])
