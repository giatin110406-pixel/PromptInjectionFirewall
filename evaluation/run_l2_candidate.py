"""
Evaluate a newly trained Layer 2 checkpoint end to end and decide whether it may replace the running one (WP7):

    python evaluation/run_l2_candidate.py                                   # v3b defaults below
    python evaluation/run_l2_candidate.py --artifacts models/l2_multilingual/artifacts_<new> --data-dir data/processed_public_<new> --tag <new>

Steps (each writes its own *_<tag> files; the running model's results are not touched):
  1. calibrate_bands.py on the dev data of the candidate's dataset  -> band_calibration_<tag>.json
  2. eval_transactions.py with those bands                          -> transactions_eval_<tag>.json
  3. eval_public.py (held-out public sets) with those bands         -> public_eval_<tag>.json   (about 20-40 min on the GPU)
  4. compare_l2_models.py --old v3 --new <tag>                      -> l2_compare_v3_vs_<tag>.json, prints SWAP or KEEP
Nothing is swapped automatically: replacing models/l2_multilingual/artifacts and the constants in firewall/orchestrator.py
is a separate, manual step.
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def run(*cmd):
    print("\n>>>", " ".join(cmd), flush=True)
    code = subprocess.call([sys.executable, *cmd], cwd=BASE_DIR, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if code:
        sys.exit(f"step failed ({code}): {' '.join(cmd)}")


def main():
    tag = arg("--tag", "v3b")
    artifacts = arg("--artifacts", f"models/l2_multilingual/artifacts_{tag}")
    data_dir = arg("--data-dir", f"data/processed_public_{tag}")
    old = arg("--old", "v3")
    if not os.path.exists(os.path.join(BASE_DIR, artifacts, "model.safetensors")) and not os.path.exists(os.path.join(BASE_DIR, artifacts, "checkpoint")):
        sys.exit(f"no checkpoint in {artifacts}: download it from Drive first")
    bands = f"evaluation/results/band_calibration_{tag}.json"
    if "--skip-calibration" not in sys.argv:
        run("evaluation/calibrate_bands.py", "--data-dir", data_dir, "--artifacts", artifacts, "--tag", tag)
    run("evaluation/eval_transactions.py", "--artifacts", artifacts, "--bands", bands, "--tag", tag)
    if "--skip-public" not in sys.argv:
        run("evaluation/eval_public.py", "--artifacts", artifacts, "--bands", bands, "--tag", tag)
    run("evaluation/compare_l2_models.py", "--old", old, "--new", tag)


if __name__ == "__main__":
    main()
