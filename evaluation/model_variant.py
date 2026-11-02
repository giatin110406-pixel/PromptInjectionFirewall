"""Build the engine around another Layer 2 checkpoint, with the score bands calibrated for it (evaluation only)."""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def engine_for(artifacts=None, bands=None):
    """bands: a band_calibration*.json from evaluation/calibrate_bands.py; its soft_block_below replaces the v3 constant."""
    from firewall.classifier import DEFAULT_ARTIFACTS, MultilingualClassifier
    from firewall.orchestrator import FirewallOrchestrator

    clf = MultilingualClassifier(artifacts_dir=artifacts or DEFAULT_ARTIFACTS)
    if clf.model is None:
        sys.exit(f"Layer 2 did not load from {artifacts}: {clf.error}")
    soft = json.load(open(bands, encoding="utf-8"))["soft_block_below"] if bands else "auto"
    return FirewallOrchestrator(layer2=clf, soft_block_below=soft), clf
