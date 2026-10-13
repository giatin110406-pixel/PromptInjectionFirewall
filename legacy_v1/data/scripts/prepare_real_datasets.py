"""Download and normalize real prompt-safety datasets for Layers 2 and 3.

Supports international benchmarks (deepset/prompt-injections, BIPIA) and
Vietnamese prompt injection datasets (tmdeptrai3012/prompt-injection-dataset-vi-en,
dangvansam/vietnamese-prompt-injection).

Unified schema:
text,label,label_binary,dataset_source,language,attack_type,normalized_text
"""
import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.vietnamese_norm import (
    clean_text,
    detect_language,
    deduplicate_and_resolve_conflicts,
)

PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
RAW_FILE = os.path.join(RAW_DIR, "prompt_injections.csv")
VIETNAMESE_SEED_FILE = os.path.join(RAW_DIR, "vietnamese_seed_samples.jsonl")

BIPIA_GPT_DATASET_ID = "MAlmasabi/Indirect-Prompt-Injection-BIPIA-GPT"
TMDEPTRAI_DATASET_ID = "tmdeptrai3012/prompt-injection-dataset-vi-en"
DANGVANSAM_DATASET_ID = "dangvansam/vietnamese-prompt-injection"


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


def _map_attack_type(raw_type: Optional[str], source: str, text: str, label: int) -> str:
    if label == 0:
        return "safe"
    if raw_type:
        rt = str(raw_type).strip().lower()
        if "leak" in rt:
            return "prompt_leaking"
        if "roleplay" in rt or "refusal bypass" in rt or "jailbreak" in rt:
            return "jailbreak_roleplay"
        if "goal hijack" in rt or "direct" in rt:
            return "direct_injection"
        if "obfuscation" in rt or "encoding" in rt:
            return "obfuscation"
        if "steganography" in rt:
            return "steganography"
        if "privilege" in rt or "override" in rt:
            return "privilege_escalation"
        if "indirect" in rt:
            return "indirect_injection"

    lower = text.lower()
    if "bipia" in source.lower() or "indirect" in source.lower():
        return "indirect_injection"
    if re.search(r"roleplay|pretend|hypothetical|fictional|persona|đóng vai|giả lập", lower):
        return "jailbreak_roleplay"
    if re.search(r"admin|root|override|bỏ qua|vượt quyền|cấp quyền", lower):
        return "privilege_escalation"
    if re.search(r"system prompt|hướng dẫn ban đầu|tiết lộ|leak", lower):
        return "prompt_leaking"
    return "direct_injection"


def _map_language(raw_lang: Optional[str], text: str) -> str:
    if raw_lang:
        rl = str(raw_lang).strip().lower()
        if "viet" in rl or rl == "vi":
            return "vi"
        if "eng" in rl or rl == "en":
            return "en"
        if "mix" in rl:
            return "mixed"
    return detect_language(text)


def _records_to_frame(
    records: Iterable[Dict[str, Any]],
    source: str,
    default_label: Optional[int] = None,
    default_language: Optional[str] = None
) -> pd.DataFrame:
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

        text_str = text.strip()
        norm_text = clean_text(text_str)

        raw_attack = _first_value(record, ("attack_type", "type", "category"))
        attack_type = _map_attack_type(raw_attack, source, text_str, label)

        raw_lang = _first_value(record, ("primary_language", "language", "lang")) or default_language
        lang = _map_language(raw_lang, text_str)

        rows.append({
            "text": text_str,
            "normalized_text": norm_text,
            "label": "SAFE" if label == 0 else "INJECTION_PROMPT",
            "dataset_source": source,
            "label_binary": label,
            "language": lang,
            "attack_type": attack_type,
        })
    return pd.DataFrame(rows)


def _load_huggingface(dataset_id: str, source: str, default_label: Optional[int] = None) -> pd.DataFrame:
    from datasets import load_dataset

    dataset = load_dataset(dataset_id)
    frames = []
    splits = list(dataset.keys())
    for split in splits:
        frames.append(_records_to_frame(dataset[split], source, default_label=default_label))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_local_csv(path: str, source: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    return _records_to_frame(frame.to_dict("records"), source)


def _load_jsonl(path: str, source: str) -> pd.DataFrame:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                try:
                    records.append(json.loads(line_str))
                except Exception:
                    continue
    return _records_to_frame(records, source)


def _bipia_gpt_records_to_frame(records: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in records:
        context = _message_text(record.get("context"))
        user_intent = _message_text(record.get("user_intent"))
        label = _normalize_label(record.get("label"))
        if not context or not user_intent or label is None:
            continue

        source = str(record.get("source") or "unknown").strip()
        full_text = f"User intent: {user_intent.strip()}\nExternal context:\n{context.strip()}"
        rows.append({
            "text": full_text,
            "normalized_text": clean_text(full_text),
            "label": "SAFE" if label == 0 else "INJECTION_PROMPT",
            "dataset_source": f"bipia_gpt:{source}",
            "label_binary": label,
            "language": "en",
            "attack_type": "safe" if label == 0 else "indirect_injection",
        })
    return pd.DataFrame(rows)


def _load_bipia_gpt_jsonl(path: str) -> pd.DataFrame:
    def records():
        with open(path, "r", encoding="utf-8") as dataset_file:
            for line_number, line in enumerate(dataset_file, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON on line {line_number} of {path}") from exc

    return _bipia_gpt_records_to_frame(records())


def _deduplicate_unambiguous_prompts(frame: pd.DataFrame) -> pd.DataFrame:
    return deduplicate_and_resolve_conflicts(frame, text_column="text", label_column="label_binary")


def load_tmdeptrai_dataset() -> pd.DataFrame:
    """Load tmdeptrai3012/prompt-injection-dataset-vi-en from HuggingFace."""
    print(f"[INFO] Loading Vietnamese & English dataset: {TMDEPTRAI_DATASET_ID}...")
    try:
        from datasets import load_dataset
        ds = load_dataset(TMDEPTRAI_DATASET_ID)
        frames = []
        for split in ds.keys():
            frames.append(_records_to_frame(ds[split], source="tmdeptrai3012_vi_en"))
        result = pd.concat(frames, ignore_index=True)
        print(f"[SUCCESS] Loaded {len(result)} samples from {TMDEPTRAI_DATASET_ID}")
        return result
    except Exception as exc:
        print(f"[WARN] Could not load {TMDEPTRAI_DATASET_ID}: {exc}")
        return pd.DataFrame()


def load_dangvansam_dataset(local_path: Optional[str] = None) -> pd.DataFrame:
    """
    Load dangvansam/vietnamese-prompt-injection from local path, HuggingFace (if token provided),
    or fallback to high-quality curated Vietnamese seed samples.
    """
    if local_path and os.path.exists(local_path):
        print(f"[INFO] Loading dangvansam dataset from local file: {local_path}")
        if local_path.endswith(".jsonl"):
            return _load_jsonl(local_path, source="dangvansam_vi_local")
        return _load_local_csv(local_path, source="dangvansam_vi_local")

    # Check data/raw default location
    default_raw = os.path.join(RAW_DIR, "dangvansam_vietnamese_prompt_injection.csv")
    if os.path.exists(default_raw):
        print(f"[INFO] Loading dangvansam dataset from {default_raw}")
        return _load_local_csv(default_raw, source="dangvansam_vi_raw")

    # Try Hugging Face
    token = os.environ.get("HF_TOKEN")
    try:
        print(f"[INFO] Attempting to load {DANGVANSAM_DATASET_ID} from Hugging Face...")
        from datasets import load_dataset
        ds = load_dataset(DANGVANSAM_DATASET_ID, token=token)
        frames = []
        for split in ds.keys():
            frames.append(_records_to_frame(ds[split], source="dangvansam_vi", default_language="vi"))
        res = pd.concat(frames, ignore_index=True)
        print(f"[SUCCESS] Loaded {len(res)} samples from {DANGVANSAM_DATASET_ID}")
        return res
    except Exception as exc:
        print(f"[INFO] Remote {DANGVANSAM_DATASET_ID} not accessible ({exc}). Using curated Vietnamese seed dataset.")
        if os.path.exists(VIETNAMESE_SEED_FILE):
            seed_df = _load_jsonl(VIETNAMESE_SEED_FILE, source="vietnamese_seed_curated")
            print(f"[SUCCESS] Loaded {len(seed_df)} curated Vietnamese samples from {VIETNAMESE_SEED_FILE}")
            return seed_df
        return pd.DataFrame()


def prepare_bipia_gpt_layer3(jsonl_path: Optional[str] = None) -> None:
    if jsonl_path:
        if not os.path.isfile(jsonl_path):
            raise FileNotFoundError(f"BIPIA JSONL file not found: {jsonl_path}")
        frame = _load_bipia_gpt_jsonl(jsonl_path)
    else:
        from datasets import load_dataset

        try:
            dataset = load_dataset(BIPIA_GPT_DATASET_ID, token=True)
        except Exception as exc:
            raise RuntimeError(
                "Could not access the gated BIPIA dataset. Accept its conditions on Hugging Face "
                "and authenticate with `hf auth login`, then retry."
            ) from exc

        split_name = "train" if "train" in dataset else next(iter(dataset.keys()))
        frame = _bipia_gpt_records_to_frame(dataset[split_name])
    if frame.empty or frame["label_binary"].nunique() < 2:
        raise ValueError("BIPIA-GPT data must contain valid examples from both labels.")

    frame = _deduplicate_unambiguous_prompts(frame)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    output_path = os.path.join(PROCESSED_DIR, "ground_truth_layer3.csv")
    frame.to_csv(output_path, index=False)
    print(f"[SUCCESS] Layer 3 dataset: {len(frame)} rows saved to {output_path}")
    print(f"[INFO] Labels:\n{frame['label_binary'].value_counts().to_string()}")


def prepare(
    include_bipia: bool = False,
    safe_csv: Optional[str] = None,
    include_vietnamese: bool = False,
    dangvansam_path: Optional[str] = None
) -> None:
    """
    Main preparation pipeline.
    Combines international benchmarks with Vietnamese prompt injection datasets.
    """
    frames: List[pd.DataFrame] = []

    # 1. International benchmark: deepset/prompt-injections
    try:
        frames.append(_load_huggingface("deepset/prompt-injections", "deepset_prompt_injections"))
    except Exception as exc:
        print(f"[WARN] Could not load deepset/prompt-injections: {exc}")

    # 2. International benchmark: BIPIA indirect injections
    if include_bipia:
        try:
            frames.append(_load_huggingface("BIPIA/indirect-prompt-injections", "bipia_indirect", default_label=1))
        except Exception as exc:
            print(f"[WARN] Could not load BIPIA indirect injections: {exc}")

    # 3. Optional user safe CSV
    if safe_csv:
        frames.append(_load_local_csv(safe_csv, "user_safe_csv"))

    # 4. Vietnamese prompt injection datasets
    if include_vietnamese:
        tm_df = load_tmdeptrai_dataset()
        if not tm_df.empty:
            frames.append(tm_df)

        dvs_df = load_dangvansam_dataset(local_path=dangvansam_path)
        if not dvs_df.empty:
            frames.append(dvs_df)

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise RuntimeError("No datasets were loaded. Check network access or provide datasets.")

    master = pd.concat(frames, ignore_index=True)

    if "language" not in master.columns:
        master["language"] = master["text"].apply(detect_language)
    if "normalized_text" not in master.columns:
        master["normalized_text"] = master["text"].apply(clean_text)
    if "attack_type" not in master.columns:
        master["attack_type"] = master.apply(
            lambda r: _map_attack_type(None, str(r.get("dataset_source", "")), str(r["text"]), int(r["label_binary"])),
            axis=1,
        )

    # Normalization, deduplication, conflict resolution
    master = deduplicate_and_resolve_conflicts(master, text_column="text", label_column="label_binary")
    if master["label_binary"].nunique() < 2:
        raise RuntimeError("The normalized dataset must contain both safe and malicious labels.")

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    # Save ground_truth.csv and ground_truth_mixed.csv
    master.to_csv(os.path.join(PROCESSED_DIR, "ground_truth.csv"), index=False)
    master.to_csv(os.path.join(PROCESSED_DIR, "ground_truth_mixed.csv"), index=False)

    try:
        from sklearn.model_selection import train_test_split
        train, test = train_test_split(master, test_size=0.2, stratify=master["label_binary"], random_state=42)
        train, validation = train_test_split(train, test_size=0.125, stratify=train["label_binary"], random_state=42)
    except ImportError as exc:
        raise RuntimeError("scikit-learn is required to create train/validation/test splits") from exc

    train.to_csv(os.path.join(PROCESSED_DIR, "real_train.csv"), index=False)
    validation.to_csv(os.path.join(PROCESSED_DIR, "real_validation.csv"), index=False)
    test.to_csv(os.path.join(PROCESSED_DIR, "real_test.csv"), index=False)

    # Layer 3 dataset preparation (subtle attacks, roleplay, prompt leaks)
    layer3 = train[train["attack_type"].isin({
        "indirect_injection", "jailbreak_roleplay", "safe", "prompt_leaking", "obfuscation"
    })]
    positive_count = int(layer3["label_binary"].sum()) if not layer3.empty else 0
    if layer3["label_binary"].nunique() < 2 or positive_count < 20:
        print("[WARN] Dedicated subtle attacks are too few; using complete train split for Layer 3.")
        layer3 = train

    layer3.to_csv(os.path.join(PROCESSED_DIR, "ground_truth_layer3.csv"), index=False)
    layer3.to_csv(os.path.join(PROCESSED_DIR, "ground_truth_layer3_mixed.csv"), index=False)

    print(f"[SUCCESS] Master dataset: {len(master)} rows")
    print(f"[INFO] Languages breakdown:\n{master['language'].value_counts().to_string()}")
    print(f"[INFO] Attack types breakdown:\n{master['attack_type'].value_counts().to_string()}")
    print(f"[INFO] Train/validation/test: {len(train)}/{len(validation)}/{len(test)}")
    print(f"[INFO] Labels:\n{master['label_binary'].value_counts().to_string()}")
    print(f"[SUCCESS] Layer 3 dataset: {len(layer3)} rows saved to ground_truth_layer3_mixed.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-bipia", action="store_true", help="Attempt to download the indirect injection dataset")
    parser.add_argument("--include-vietnamese", action="store_true", default=True, help="Include Vietnamese prompt injection datasets")
    parser.add_argument("--dangvansam-path", help="Optional local path to dangvansam dataset (CSV or JSONL)")
    parser.add_argument(
        "--bipia-gpt-layer3",
        nargs="?",
        const="",
        metavar="JSONL",
        help="Prepare BIPIA + GPT-4o-mini for Layer 3 only",
    )
    parser.add_argument("--safe-csv", help="Optional CSV containing safe prompts")
    args = parser.parse_args()

    if args.bipia_gpt_layer3 is not None:
        prepare_bipia_gpt_layer3(args.bipia_gpt_layer3 or None)
    else:
        prepare(
            include_bipia=args.include_bipia,
            safe_csv=args.safe_csv,
            include_vietnamese=args.include_vietnamese,
            dangvansam_path=args.dangvansam_path,
        )