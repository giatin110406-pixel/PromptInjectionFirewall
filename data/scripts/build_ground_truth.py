"""
Merge raw datasets and synthetic datasets into a standardized ground truth dataset.
Output: data/processed/ground_truth.csv
Labels: [SAFE, INJECTION_PROMPT, INJECTION_PAYLOAD, PRIVILEGE_ESCALATION]
Binary label: label_binary (0 = SAFE, 1 = MALICIOUS)
"""
import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_FILE = os.path.join(BASE_DIR, "raw", "prompt_injections.csv")
SYNTHETIC_FILE = os.path.join(BASE_DIR, "synthetic", "synthetic_jailbreaks.csv")
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
    frames = []

    # 1. Load Raw Dataset if exists
    if os.path.exists(RAW_FILE):
        df_raw = pd.read_csv(RAW_FILE)
        df_raw["label"] = df_raw["label"].apply(normalize_label)
        df_raw["dataset_source"] = "raw_download"
        frames.append(df_raw[["text", "label", "dataset_source"]])
        print(f"[INFO] Loaded {len(df_raw)} records from {RAW_FILE}")

    # 2. Load Synthetic Dataset if exists
    if os.path.exists(SYNTHETIC_FILE):
        df_syn = pd.read_csv(SYNTHETIC_FILE)
        df_syn["label"] = df_syn["label"].apply(normalize_label)
        df_syn["dataset_source"] = "synthetic_generator"
        frames.append(df_syn[["text", "label", "dataset_source"]])
        print(f"[INFO] Loaded {len(df_syn)} records from {SYNTHETIC_FILE}")

    if not frames:
        raise FileNotFoundError("Neither raw nor synthetic datasets found. Run download_datasets.py and generate_synthetic.py first.")

    combined = pd.concat(frames, ignore_index=True)
    combined["text"] = combined["text"].astype(str).str.strip()
    
    # Drop empty and duplicates
    combined = combined[combined["text"].str.len() > 3]
    combined = combined.drop_duplicates(subset=["text"]).reset_index(drop=True)

    # Add binary classification column (0 for SAFE, 1 for any attack)
    combined["label_binary"] = combined["label"].apply(lambda l: 0 if l == "SAFE" else 1)

    combined.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[SUCCESS] Ground truth built and saved to {OUTPUT_FILE}")
    print(f"Total clean samples: {len(combined)}")
    print("\n--- Multiclass Distribution ---")
    print(combined["label"].value_counts())
    print("\n--- Binary Distribution (0=SAFE, 1=MALICIOUS) ---")
    print(combined["label_binary"].value_counts())

if __name__ == "__main__":
    main()
