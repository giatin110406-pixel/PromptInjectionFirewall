"""Download and normalize real prompt-safety datasets for Layers 2 and 3.

The output schema is compatible with the existing feature builder:
text,label,dataset_source,label_binary
"""
import argparse
import os
import re
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
RAW_FILE = os.path.join(BASE_DIR, "data", "raw", "prompt_injections.csv")


def _first_value(record: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None and value != "":
            return value
    return None


def _message_text(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                role = str(item.get("role", item.get("from", ""))).lower()
                content = item.get("content", item.get("value", item.get("text", "")))
                if role in {"user", "human", ""} and content:
                    parts.append(str(content))
        return "\n".join(parts) or None
    if isinstance(value, dict):
        return _message_text(value.get("content", value.get("text", "")))
    return None


def _normalize_label(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not pd.isna(value):
        return int(float(value) != 0)
    if value is None or pd.isna(value):
        return None
    label = str(value).strip().lower()
    if label in {"0", "false", "safe", "benign", "normal", "harmless", "clean"}:
        return 0
    if label in {"1", "true", "attack", "injection", "malicious", "unsafe", "harmful", "jailbreak"}:
        return 1
    if any(word in label for word in ("inject", "attack", "malicious", "jailbreak", "harmful")):
        return 1
    return None


def _attack_type(source: str, text: str, label: int) -> str:
    lower = text.lower()
    if label == 0:
        return "safe"
    if "bipia" in source.lower() or "indirect" in source.lower():
        return "indirect_injection"
    if re.search(r"roleplay|pretend|hypothetical|fictional|persona", lower):
        return "jailbreak_roleplay"
    return "direct_injection"


def _records_to_frame(records: Iterable[Dict[str, Any]], source: str, default_label: Optional[int] = None) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in records:
        raw_text = _first_value(record, ("text", "prompt", "question", "instruction", "content", "query", "messages"))
        text = _message_text(raw_text)
        if not text or len(text.strip()) < 4:
            continue
        raw_label = _first_value(record, ("label_binary", "label", "is_attack", "injection", "malicious", "attack"))
        label = _normalize_label(raw_label)
        if label is None:
            label = default_label
        if label is None:
            continue
        text = text.strip()
        rows.append({
            "text": text,
            "label": "SAFE" if label == 0 else "INJECTION_PROMPT",
            "dataset_source": source,
            "label_binary": label,
            "attack_type": _attack_type(source, text, label),
        })
    return pd.DataFrame(rows)


def _load_huggingface(dataset_id: str, source: str, default_label: Optional[int] = None) -> pd.DataFrame:
    from datasets import load_dataset

    dataset = load_dataset(dataset_id)
    split = "train" if "train" in dataset else next(iter(dataset.keys()))
    return _records_to_frame(dataset[split], source, default_label=default_label)


def _load_local_csv(path: str, source: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    return _records_to_frame(frame.to_dict("records"), source)


def prepare(include_bipia: bool, safe_csv: Optional[str]) -> None:
    frames: List[pd.DataFrame] = []

    try:
        frames.append(_load_huggingface("deepset/prompt-injections", "deepset_prompt_injections"))
    except Exception as exc:
        print(f"[WARN] Could not load deepset/prompt-injections: {exc}")

    if include_bipia:
        try:
            frames.append(_load_huggingface("BIPIA/indirect-prompt-injections", "bipia_indirect", default_label=1))
        except Exception as exc:
            print(f"[WARN] Could not load BIPIA indirect injections: {exc}")

    if safe_csv:
        frames.append(_load_local_csv(safe_csv, "user_safe_csv"))

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise RuntimeError("No datasets were loaded. Check network access or provide --safe-csv.")

    master = pd.concat(frames, ignore_index=True)
    master = master.drop_duplicates(subset=["text"]).reset_index(drop=True)
    if master["label_binary"].nunique() < 2:
        raise RuntimeError("The normalized dataset must contain both safe and malicious labels.")

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    master.to_csv(os.path.join(PROCESSED_DIR, "ground_truth.csv"), index=False)

    try:
        from sklearn.model_selection import train_test_split
        train, test = train_test_split(master, test_size=0.2, stratify=master["label_binary"], random_state=42)
        train, validation = train_test_split(train, test_size=0.125, stratify=train["label_binary"], random_state=42)
    except ImportError as exc:
        raise RuntimeError("scikit-learn is required to create train/validation/test splits") from exc

    train.to_csv(os.path.join(PROCESSED_DIR, "real_train.csv"), index=False)
    validation.to_csv(os.path.join(PROCESSED_DIR, "real_validation.csv"), index=False)
    test.to_csv(os.path.join(PROCESSED_DIR, "real_test.csv"), index=False)

    layer3 = train[train["attack_type"].isin({"indirect_injection", "jailbreak_roleplay", "safe"})]
    positive_count = int(layer3["label_binary"].sum()) if not layer3.empty else 0
    if layer3["label_binary"].nunique() < 2 or positive_count < 20:
        print("[WARN] Dedicated subtle attacks are too few; using the complete real training split for Layer 3.")
        layer3 = train
    layer3.to_csv(os.path.join(PROCESSED_DIR, "ground_truth_layer3.csv"), index=False)

    print(f"[SUCCESS] Master dataset: {len(master)} rows")
    print(f"[INFO] Train/validation/test: {len(train)}/{len(validation)}/{len(test)}")
    print(f"[INFO] Labels:\n{master['label_binary'].value_counts().to_string()}")
    print(f"[SUCCESS] Layer 3 dataset: {len(layer3)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-bipia", action="store_true", help="Attempt to download the indirect injection dataset")
    parser.add_argument("--safe-csv", help="Optional CSV containing safe prompts")
    args = parser.parse_args()
    prepare(include_bipia=args.include_bipia, safe_csv=args.safe_csv)