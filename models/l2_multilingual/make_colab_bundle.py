"""
Pack what Colab needs to train Layer 2 into one small zip (about 10 MB):

    python models/l2_multilingual/make_colab_bundle.py             ->  l2_colab_bundle.zip (dataset v2, AI-generated)
    python models/l2_multilingual/make_colab_bundle.py --public    ->  l2_colab_bundle_public.zip (dataset v3, public data)

Contents (same relative paths as the project, so train.py runs unchanged):
    models/l2_multilingual/{train,chunking,metrics}.py
    data/processed/dataset_v2_{train,validation,test}.csv          (--public: data/processed_public/ instead)
"""
import argparse
import os
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CODE = [
    "models/l2_multilingual/train.py",
    "models/l2_multilingual/chunking.py",
    "models/l2_multilingual/metrics.py",
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true", help="bundle dataset v3 (data/processed_public) instead of dataset v2")
    args = parser.parse_args()
    data_dir = "data/processed_public" if args.public else "data/processed"
    files = CODE + [f"{data_dir}/dataset_v2_{s}.csv" for s in ("train", "validation", "test")]
    out = os.path.join(BASE, "l2_colab_bundle_public.zip" if args.public else "l2_colab_bundle.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for rel in files:
            bundle.write(os.path.join(BASE, rel), rel)
    print(f"{out}: {os.path.getsize(out) / 1e6:.1f} MB, {len(files)} files")
