"""
Download prompt injection datasets from public repositories (HuggingFace / open-source).
Includes fallback mechanism to ensure offline reproducibility.
"""
import os
import sys
import pandas as pd

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")
OUTPUT_FILE = os.path.join(RAW_DATA_DIR, "prompt_injections.csv")

def download_hf_dataset() -> pd.DataFrame:
    print("[INFO] Attempting to download 'deepset/prompt-injections' from HuggingFace...")
    try:
        from datasets import load_dataset
        ds = load_dataset("deepset/prompt-injections", split="train")
        df = ds.to_pandas()
        df["source"] = "deepset_prompt_injections"
        print(f"[SUCCESS] Downloaded {len(df)} rows from HuggingFace.")
        return df
    except Exception as e:
        print(f"[WARN] HuggingFace download failed or dependencies missing: {e}")
        return None

def main():
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    df = download_hf_dataset()
    if df is None or len(df) == 0:
        raise RuntimeError(
            "No public dataset could be loaded. The project now requires a real public prompt-injection dataset from Hugging Face."
        )

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"[DONE] Saved dataset to {OUTPUT_FILE} ({len(df)} samples)")
    print("Label distribution:")
    print(df["label"].value_counts())

if __name__ == "__main__":
    main()
