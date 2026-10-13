"""
Count the datasets each layer uses and write PrepareForBCTĐ2/results/datasets_summary.md (+ .json).

    python PrepareForBCTĐ2/tools/dataset_stats.py

Sizes come from the files on disk, so rerun after rebuilding the dataset or the Layer 1 index.
"""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "models", "l2_multilingual"))
RESULTS = os.path.join(ROOT, "PrepareForBCTĐ2", "results")


def md_table(frame: pd.DataFrame) -> str:
    cols = [str(c) for c in frame.columns]
    rows = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in frame.iterrows():
        rows.append("| " + " | ".join(f"{v:,}" if isinstance(v, (int,)) else str(v) for v in row.tolist()) + " |")
    return "\n".join(rows)


def main() -> None:
    out = {}
    parts = []
    frames = []
    for split in ("train", "validation", "test"):
        frames.append(pd.read_csv(os.path.join(ROOT, "data", "processed", f"dataset_v2_{split}.csv"), keep_default_na=False).assign(split=split))
    data = pd.concat(frames, ignore_index=True)
    out["dataset_v2_rows"] = {s: int((data.split == s).sum()) for s in ("train", "validation", "test")}
    out["dataset_v2_total"] = int(len(data))

    by_split = data.groupby(["split", "lang"]).size().unstack(fill_value=0).reindex(["train", "validation", "test"])
    by_split["tổng"] = by_split.sum(axis=1)
    parts += ["### dataset_v2 theo split và ngôn ngữ", md_table(by_split.reset_index().rename(columns={"split": "split"}))]

    by_source = data.groupby(["source", "split"]).size().unstack(fill_value=0)[["train", "validation", "test"]]
    by_source["tổng"] = by_source.sum(axis=1)
    by_source["tấn công"] = data[data.label_binary == 1].groupby("source").size()
    by_source["bình thường"] = data[data.label_binary == 0].groupby("source").size()
    parts += ["### dataset_v2 theo nguồn", md_table(by_source.reset_index())]
    out["dataset_v2_by_source"] = {k: int(v) for k, v in data.groupby("source").size().items()}

    # Layer 1 index
    index_dir = os.path.join(ROOT, "models", "layer1_prefilter", "index")
    with open(os.path.join(index_dir, "entries.json"), "r", encoding="utf-8") as handle:
        entries = json.load(handle)
    idx = pd.DataFrame(entries)
    idx["origin"] = idx["source"].str.replace("+noaccent", "", regex=False)
    idx["twin"] = idx["source"].str.endswith("+noaccent")
    table = idx.groupby("origin").agg(mẫu=("text", "size"), bản_không_dấu=("twin", "sum")).reset_index()
    parts += [f"### Chỉ mục ngữ nghĩa của L1 ({len(idx):,} mẫu: {int((idx.label == 1).sum()):,} tấn công, {int((idx.label == 0).sum()):,} bình thường)",
              md_table(table)]
    out["layer1_index"] = {"entries": int(len(idx)), "attack": int((idx.label == 1).sum()), "benign": int((idx.label == 0).sum())}

    # Layer 2 windows (tokenizer of the shipped checkpoint)
    ckpt = os.path.join(ROOT, "models", "l2_multilingual", "artifacts", "checkpoint")
    if os.path.isdir(ckpt):
        from chunking import balance_chunks, build_examples
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(ckpt)
        offsets = lambda t: [tuple(o) for o in tok(t, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]]
        windows = {}
        for split in ("train", "validation", "test"):
            rows = data[data.split == split].to_dict("records")
            examples = build_examples(rows, offsets, 200, 128)
            if split == "train":
                examples = balance_chunks(examples, seed=42, ratio=1.0)
            windows[split] = {"windows": len(examples), "attack": sum(e["label"] for e in examples)}
        out["layer2_windows"] = windows
        parts += ["### Cửa sổ huấn luyện của L2 (200 token, bước 128; train được cân bằng 1:1)",
                  md_table(pd.DataFrame([{"split": s, "cửa sổ": v["windows"], "tấn công": v["attack"], "bình thường": v["windows"] - v["attack"]}
                                         for s, v in windows.items()]))]

    # held-out evaluation sets
    vi = pd.read_csv(os.path.join(ROOT, "data", "eval", "vi_test_v1.csv"), keep_default_na=False, encoding="utf-8-sig")
    ext = pd.read_csv(os.path.join(ROOT, "data", "eval", "tmdeptrai_external_test.csv"), keep_default_na=False)
    out["eval_sets"] = {"vi_test_v1": int(len(vi)), "tmdeptrai_external_test": int(len(ext))}
    parts += ["### Tập đo riêng (không bao giờ dùng để train)",
              md_table(pd.DataFrame([{"tập": "vi_test_v1", "dòng": len(vi), "tấn công": int((vi.label == "attack").sum()), "bình thường": int((vi.label != "attack").sum())},
                                     {"tập": "tmdeptrai_external_test", "dòng": len(ext), "tấn công": int(ext.label_binary.sum()), "bình thường": int((ext.label_binary == 0).sum())}]))]

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "datasets_summary.md"), "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(parts) + "\n")
    with open(os.path.join(RESULTS, "datasets_summary.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, ensure_ascii=False)
    print("\n\n".join(parts))


if __name__ == "__main__":
    main()
