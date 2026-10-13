"""
Create the ground-truth dataset from public prompt-injection data only.
Synthetic or hand-written fallback data is intentionally excluded.
Output: data/processed/ground_truth.csv
"""
import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_FILE = os.path.join(BASE_DIR, "raw", "prompt_injections.csv")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DIR, "ground_truth.csv")

VALID_LABELS = {"SAFE", "INJECTION_PROMPT", "INJECTION_PAYLOAD", "PRIVILEGE_ESCALATION"}


def normalize_label(val) -> str:
    if pd.isna(val):
        return "SAFE"
    s = str(val).strip().upper()
    if s in ["0", "SAFE", "BENIGN", "NORMAL"]:
        return "SAFE"
    if s in ["1", "INJECTION", "ATTACK", "MALICIOUS", "INJECTION_PROMPT"]:
        return "INJECTION_PROMPT"
    if s in ["INJECTION_PAYLOAD", "PAYLOAD"]:
        return "INJECTION_PAYLOAD"
    if s in ["PRIVILEGE_ESCALATION", "ESCALATION"]:
        return "PRIVILEGE_ESCALATION"
    return "INJECTION_PROMPT"


def main():
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    if not os.path.exists(RAW_FILE):
        raise FileNotFoundError(
            f"Public prompt-injection dataset not found at {RAW_FILE}. Run data/scripts/download_datasets.py first."
        )

    df = pd.read_csv(RAW_FILE)
    df["label"] = df["label"].apply(normalize_label)
    df["dataset_source"] = "public_dataset"
    df = df[["text", "label", "dataset_source"]]

    print(f"[INFO] Loaded {len(df)} records from {RAW_FILE}")

    df["text"] = df["text"].astype(str).str.strip()
    df = df[df["text"].str.len() > 3]
    df = df.drop_duplicates(subset=["text"]).reset_index(drop=True)
    df["label_binary"] = df["label"].apply(lambda l: 0 if l == "SAFE" else 1)

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[SUCCESS] Ground truth built and saved to {OUTPUT_FILE}")
    print(f"Total clean samples: {len(df)}")
    print("\n--- Multiclass Distribution ---")
    print(df["label"].value_counts())
    print("\n--- Binary Distribution (0=SAFE, 1=MALICIOUS) ---")
    print(df["label_binary"].value_counts())


if __name__ == "__main__":
    main()
