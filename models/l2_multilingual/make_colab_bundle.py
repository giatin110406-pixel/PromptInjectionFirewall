"""
Pack what Colab needs to train Layer 2 into one small zip (about 10 MB):

    python models/l2_multilingual/make_colab_bundle.py      ->  l2_colab_bundle.zip (project root)

Contents (same relative paths as the project, so train.py runs unchanged):
    models/l2_multilingual/{train,chunking,metrics}.py
    data/processed/dataset_v2_{train,validation,test}.csv
"""
import os
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = [
    "models/l2_multilingual/train.py",
    "models/l2_multilingual/chunking.py",
    "models/l2_multilingual/metrics.py",
    "data/processed/dataset_v2_train.csv",
    "data/processed/dataset_v2_validation.csv",
    "data/processed/dataset_v2_test.csv",
]

if __name__ == "__main__":
    out = os.path.join(BASE, "l2_colab_bundle.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for rel in FILES:
            bundle.write(os.path.join(BASE, rel), rel)
    print(f"{out}: {os.path.getsize(out) / 1e6:.1f} MB, {len(FILES)} files")
