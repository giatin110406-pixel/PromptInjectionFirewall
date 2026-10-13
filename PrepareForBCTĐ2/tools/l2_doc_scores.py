"""
Save the document-level Layer 2 score of every text in the evaluation sets, so threshold and band studies (Layer 3)
do not need the model again.

    python PrepareForBCTĐ2/tools/l2_doc_scores.py

Writes results/l2_doc_scores.csv: set, text_hash, label_binary, lang, score, top_window_text (borderline later).
Sets: validation, test (dataset_v2) and the dev / test halves of external and vi_test_v1 (see evaluation/eval_layer1.py).
Rule for the Layer 3 study: choose the band on validation + dev halves, report on test + test halves.
"""
import hashlib
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evaluation"))

from eval_layer1 import load_set  # noqa: E402
from firewall.classifier import MultilingualClassifier  # noqa: E402

SETS = ["validation", "external_dev", "vi_dev", "test", "external_test", "vi_test"]


def main() -> None:
    l2 = MultilingualClassifier()
    assert l2.model is not None, l2.error
    rows = []
    for name in SETS:
        frame = load_set(name)
        for text, label, lang in zip(frame["text"], frame["label_binary"], frame["lang"]):
            scores = l2.window_scores(text)
            rows.append({"set": name, "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
                         "label_binary": int(label), "lang": lang, "score": round(max(scores), 5)})
        print(name, len(frame))
    path = os.path.join(ROOT, "PrepareForBCTĐ2", "results", "l2_doc_scores.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    print("wrote", path, len(rows))


if __name__ == "__main__":
    main()
