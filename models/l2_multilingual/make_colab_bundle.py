"""
Pack what Colab needs to train Layer 2 into one small zip (about 10 MB):

    python models/l2_multilingual/make_colab_bundle.py             ->  l2_colab_bundle.zip (dataset v2, AI-generated)
    python models/l2_multilingual/make_colab_bundle.py --public    ->  l2_colab_bundle_public.zip (dataset v3, public data)
    python models/l2_multilingual/make_colab_bundle.py --v3b       ->  l2_colab_bundle_v3b.zip (dataset v3b, packed as data/processed_public
                                                                       so colab_train_public.ipynb runs unchanged)
    python models/l2_multilingual/make_colab_bundle.py --v3c       ->  l2_colab_bundle_v3c.zip (dataset v3c = v3b + H5, packed the same way)

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
    parser.add_argument("--v3b", action="store_true", help="bundle dataset v3b (data/processed_public_v3b)")
    parser.add_argument("--v3c", action="store_true", help="bundle dataset v3c (data/processed_public_v3c)")
    args = parser.parse_args()
    data_dir = "data/processed_public" if (args.public or args.v3b or args.v3c) else "data/processed"
    source_dir = "data/processed_public_v3c" if args.v3c else "data/processed_public_v3b" if args.v3b else data_dir
    pairs = [(rel, rel) for rel in CODE] + [(f"{source_dir}/dataset_v2_{s}.csv", f"{data_dir}/dataset_v2_{s}.csv")
                                            for s in ("train", "validation", "test")]
    name = "l2_colab_bundle_v3c.zip" if args.v3c else "l2_colab_bundle_v3b.zip" if args.v3b else "l2_colab_bundle_public.zip" if args.public else "l2_colab_bundle.zip"
    out = os.path.join(BASE, name)
    files = [arc for _, arc in pairs]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for src, arc in pairs:
            bundle.write(os.path.join(BASE, src), arc)
    print(f"{out}: {os.path.getsize(out) / 1e6:.1f} MB, {len(files)} files")
