"""Second round: leakage inside dataset_v2, regex facts, and what build_dataset_v2 really reads."""
import json
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
n = lambda t: re.sub(r"\s+", " ", str(t).strip().lower())

frames = [pd.read_csv(f"data/processed/dataset_v2_{s}.csv", keep_default_na=False).assign(split=s) for s in ("train", "validation", "test")]
data = pd.concat(frames)

print("== shared inserted sentences between train and test")
tr_ins = {n(t): (l, a) for t, l, a in zip(data[data.split == "train"].insert_text, data[data.split == "train"].label_binary, data[data.split == "train"].attack_type) if t}
te = data[(data.split == "test") & (data.insert_text != "")]
te["in_train"] = te.insert_text.map(lambda t: n(t) in tr_ins)
print(te.groupby(["label_binary", "variant"]).agg(rows=("text", "size"), insert_seen_in_train=("in_train", "sum")).to_string())
print("test rows total", int((data.split == "test").sum()), "| rows whose inserted sentence also occurs in train:", int(te.in_train.sum()), f"({te.in_train.mean():.0%} of rows that have an inserted sentence)")
print("benign test rows", int(((data.split == "test") & (data.label_binary == 0)).sum()), "| benign_insert test rows", int(((data.split == "test") & (data.variant == "benign_insert")).sum()))
at = data[(data.split == "test") & (data.label_binary == 1) & (data.insert_text != "")]
print("attack test rows with insert_text", len(at), "seen in train", int(at.insert_text.map(lambda t: n(t) in tr_ins).sum()))
shared_attack = [t for t in set(map(n, at.insert_text)) if t in tr_ins]
print("distinct attack insert sentences shared with train:", len(shared_attack))
for t in shared_attack[:3]:
    print("   e.g.", t[:110])

print("== L2 test windows: false-positive rate by variant (from test_scores.csv, threshold from temperature.json)")
cfg = json.load(open("models/l2_multilingual/artifacts/temperature.json", encoding="utf-8"))
sc = pd.read_csv("models/l2_multilingual/artifacts/test_scores.csv", keep_default_na=False)
print(list(sc.columns))
sc["pred"] = sc.score >= cfg["threshold"]
safe = sc[sc.label == 0]
print(safe.groupby("variant").agg(windows=("label", "size"), false_positives=("pred", "sum")).assign(fpr=lambda d: (d.false_positives / d.windows).round(4)).to_string())
print("overall safe-window FPR", round(safe.pred.mean(), 4), "| excluding benign_insert", round(safe[safe.variant != "benign_insert"].pred.mean(), 4), "on", int((safe.variant != "benign_insert").sum()), "windows")

print("== build_dataset_v2 inputs")
b = open("data/scripts/build_dataset_v2.py", encoding="utf-8").read()
for token in ("dataset_for_huggingface", "BIPIA", "bipia", "tmdeptrai", "docs_vi", "verify_vi", "chat_vi"):
    print(token, [m.start() for m in re.finditer(token, b)][:3])
for m in re.finditer(r"dataset_for_huggingface[^\n]*", b):
    print("  >", m.group(0)[:160])

print("== L1 regex: the '+2 English patterns' and unaccented handling")
l1 = open("firewall/layer1.py", encoding="utf-8").read()
for m in re.finditer(r"(?m)^(.*(?:EXTRA|extra|_EN_|English|ENGLISH).*)$", l1):
    print("  layer1:", m.group(1)[:140])
bs = open("firewall/baseline.py", encoding="utf-8").read()
print("  baseline mentions unaccent:", len(re.findall("unaccent|remove_vietnamese_accents", bs)), "| layer1 mentions unaccent:", len(re.findall("unaccent|ACCENT_FREE", l1)))
from firewall import baseline  # noqa: E402
print("  RegexBaseline default pattern count:", len(baseline.DEFAULT_BASELINE_PATTERNS), "soft", len(baseline.SOFT_BASELINE_PATTERNS), "hint", len(baseline.ESCALATE_HINT_PATTERNS))
import inspect  # noqa: E402
from firewall import layer1  # noqa: E402
src = inspect.getsource(layer1)
print("  names in layer1 with PATTERN:", sorted(set(re.findall(r"\b[A-Z_]*PATTERN[A-Z_]*\b", src))))
for name in sorted(set(re.findall(r"\b[A-Z_]*PATTERN[A-Z_]*\b", src))):
    obj = getattr(layer1, name, None)
    if isinstance(obj, (list, tuple)):
        print("   ", name, len(obj))

print("== is any text duplicated within train")
tr = data[data.split == "train"]
print("duplicate texts within train:", int(tr.text.map(n).duplicated().sum()))
