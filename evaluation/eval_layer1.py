"""
Calibrate and evaluate Layer 1.

    python evaluation/eval_layer1.py calibrate     # choose thresholds on the DEV sets
    python evaluation/eval_layer1.py report        # measure the shipped layer on the TEST sets
    python evaluation/eval_layer1.py latency       # time the layer

Protocol (so the numbers can be trusted):
  - the index holds TRAIN data only (models/layer1_prefilter/build_index.py);
  - thresholds are chosen on three DEV sets: dataset_v2 validation, and a dev half of each external
    set. Choosing on validation alone looked fine (0.17% extra false positives) and then failed on
    text from another author (9%): the validation split shares its generator with the training
    data, so it cannot show how the layer behaves on shifted text;
  - the rule: the highest average recall whose extra false positive rate (beyond what the regex
    already blocks) stays under a cap on EVERY dev set;
  - the report measures the layer exactly as shipped, text by text through `Layer1Prefilter.check`,
    on the TEST sets: dataset_v2 test, and the other half of each external set.

Sets:
  validation / test      dataset_v2: held-out documents AND held-out attack templates
  external_dev / _test   tmdeptrai3012 test split: another author, another generator, never trained on
  vi_dev / vi_test       vi_test_v1: drafted by Claude, labels NOT yet cross-reviewed by the team. Same
                         author as the seed banks, so treat its numbers as optimistic.
  The two halves of an external set are split by a hash of the text, so they never overlap.
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from firewall.layer1 import DEFAULT_INDEX_DIR, Layer1Prefilter  # noqa: E402
from firewall.normalize import candidate_views  # noqa: E402
from firewall.signature_index import Thresholds  # noqa: E402
from firewall.text_units import prepare_unit, split_units  # noqa: E402
from models.l2_multilingual.metrics import binary_metrics  # noqa: E402

PROCESSED = os.path.join(BASE_DIR, "data", "processed")
EVAL_DIR = os.path.join(BASE_DIR, "data", "eval")
RESULTS = os.path.join(BASE_DIR, "evaluation", "results")

SIM_GRID = [round(float(x), 2) for x in np.arange(0.40, 0.99, 0.01)]
MARGIN_GRID = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.15, 0.20]
DEV_SETS = {"validation": 0.005, "external_dev": 0.02, "vi_dev": 0.02}   # set -> extra FPR cap
TEST_SETS = ["test", "external_test", "vi_test"]


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def _read_set(name: str) -> pd.DataFrame:
    if name in ("validation", "test"):
        frame = pd.read_csv(os.path.join(PROCESSED, f"dataset_v2_{name}.csv"))
    elif name == "external":
        frame = pd.read_csv(os.path.join(EVAL_DIR, "tmdeptrai_external_test.csv"))
    elif name == "vi":
        raw = pd.read_csv(os.path.join(EVAL_DIR, "vi_test_v1.csv"), dtype=str, keep_default_na=False, encoding="utf-8-sig")
        frame = pd.DataFrame({
            "text": raw["text"], "label_binary": (raw["label"] == "attack").astype(int), "lang": "vi",
            "source": "vi_test_v1", "attack_type": raw["attack_type"], "variant": raw["style"] + "/" + raw["difficulty"],
        })
    else:
        raise ValueError(f"unknown set {name}")
    for column in ("lang", "source", "attack_type", "variant"):
        if column not in frame.columns:
            frame[column] = ""
    return frame[["text", "label_binary", "lang", "source", "attack_type", "variant"]].reset_index(drop=True)


def _half(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % 2


def load_set(name: str) -> pd.DataFrame:
    """validation, test, external_dev, external_test, vi_dev, vi_test. The dev/test halves never overlap."""
    if name in ("validation", "test"):
        return _read_set(name)
    base, _, half = name.rpartition("_")
    if base in ("external", "vi") and half in ("dev", "test"):
        frame = _read_set(base)
        keep = frame["text"].map(_half) == (0 if half == "dev" else 1)
        return frame[keep].reset_index(drop=True)
    raise ValueError(f"unknown set {name}")


# ----------------------------------------------------------------------------
# Calibration
# ----------------------------------------------------------------------------
def unit_arrays(layer: Layer1Prefilter, texts: Sequence[str], batch: int = 2048) -> Tuple[np.ndarray, np.ndarray]:
    """
    For every text, the attack similarity and the margin of each of its units, padded to the longest
    text with -inf. Unit scores are computed once and reused for the whole threshold grid.
    """
    per_text_units = [split_units(layer.semantic_text(candidate_views(t), t), layer.max_units) for t in texts]
    flat = [u for units in per_text_units for u in units]
    vectors = np.zeros((0, layer.index.vectors.shape[1]), dtype=np.float32)
    chunks = [layer.embedder.encode([prepare_unit(u) for u in flat[i:i + batch]]) for i in range(0, len(flat), batch)]
    if chunks:
        vectors = np.concatenate(chunks)
    width = max((len(u) for u in per_text_units), default=1) or 1
    attack = np.full((len(texts), width), -np.inf, dtype=np.float32)
    margin = np.full((len(texts), width), -np.inf, dtype=np.float32)
    cursor = 0
    for row, units in enumerate(per_text_units):
        if not units:
            continue
        scores = layer.index.score_vectors(units, vectors[cursor:cursor + len(units)])
        cursor += len(units)
        attack[row, :len(units)] = [s.attack_sim for s in scores]
        margin[row, :len(units)] = [s.margin for s in scores]
    return attack, margin


def flags_for(attack: np.ndarray, margin: np.ndarray, sim: float, min_margin: float) -> np.ndarray:
    """True for texts having at least one unit with attack similarity >= sim and margin >= min_margin."""
    return ((attack >= sim) & (margin >= min_margin)).any(axis=1)


def regex_blocked(texts: Sequence[str]) -> np.ndarray:
    layer = Layer1Prefilter(use_vector=False)
    return np.array([layer.check(t)["decision"] == "BLOCK" for t in texts])


def calibrate_multi(sets: Sequence[Dict[str, Any]], escalate_budget: float = 0.12) -> Dict[str, Any]:
    """
    Pick (block_sim, block_margin) maximising the AVERAGE recall over the dev sets, subject to an
    extra-false-positive cap on EVERY set. "Extra" counts safe texts the regex did not already
    block, so the semantic part is judged on what it adds. Then pick escalate_sim: the lowest
    similarity that sends at most `escalate_budget` of the remaining safe texts (averaged over the
    sets) to Layer 2.

    Each set is a dict: name, attack, margin, labels, regex_hit, cap.
    """
    prepared = []
    for item in sets:
        labels = np.asarray(item["labels"]).astype(int)
        prepared.append({**item, "attacks": labels == 1, "safe": labels == 0,
                         "safe_open": (labels == 0) & ~item["regex_hit"]})

    def recall_of(item, vec):
        return float(((vec | item["regex_hit"]) & item["attacks"]).sum() / max(item["attacks"].sum(), 1))

    best: Optional[Dict[str, Any]] = None
    for sim in SIM_GRID:
        for min_margin in MARGIN_GRID:
            fprs, recalls, feasible = {}, {}, True
            for item in prepared:
                vec = flags_for(item["attack"], item["margin"], sim, min_margin)
                fprs[item["name"]] = float((vec & item["safe_open"]).sum() / max(item["safe_open"].sum(), 1))
                if fprs[item["name"]] > item["cap"]:
                    feasible = False
                    break
                recalls[item["name"]] = recall_of(item, vec)
            if not feasible:
                continue
            key = (float(np.mean(list(recalls.values()))), -sum(fprs.values()), sim)
            if best is None or key > best["key"]:
                best = {"key": key, "block_sim": sim, "block_margin": min_margin, "recalls": recalls, "fprs": fprs}
    if best is None:  # nothing meets every cap: block nothing semantically rather than block customers
        best = {"key": (0.0, 0.0, 1.0), "block_sim": 0.99, "block_margin": 0.99,
                "recalls": {i["name"]: recall_of(i, np.zeros(len(i["labels"]), dtype=bool)) for i in prepared},
                "fprs": {i["name"]: 0.0 for i in prepared}}

    def esc_share(sim: float) -> float:
        shares = []
        for item in prepared:
            block = flags_for(item["attack"], item["margin"], best["block_sim"], best["block_margin"]) | item["regex_hit"]
            esc = flags_for(item["attack"], item["margin"], sim, 0.0) & ~block
            remaining = item["safe"] & ~block
            shares.append(float((esc & item["safe"]).sum() / max(remaining.sum(), 1)))
        return float(np.mean(shares))

    escalate_sim = best["block_sim"]
    for sim in SIM_GRID:
        if esc_share(sim) <= escalate_budget:
            escalate_sim = sim
            break
    escalate_sim = min(escalate_sim, best["block_sim"])
    return {"block_sim": best["block_sim"], "block_margin": best["block_margin"], "escalate_sim": escalate_sim,
            "dev_mean_recall": round(best["key"][0], 4),
            "dev_recall": {k: round(v, 4) for k, v in best["recalls"].items()},
            "dev_extra_fpr": {k: round(v, 4) for k, v in best["fprs"].items()},
            "caps": {i["name"]: i["cap"] for i in prepared}, "escalate_budget": escalate_budget,
            "dev_escalate_share_of_safe": round(esc_share(escalate_sim), 4)}


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
def run_layer(layer: Layer1Prefilter, frame: pd.DataFrame) -> pd.DataFrame:
    """Decision of the shipped layer for every row, with timing."""
    rows = []
    for text in frame["text"]:
        start = time.perf_counter()
        result = layer.check(text)
        rows.append({
            "decision": result["decision"], "reason": result["reason"].split(":")[0],
            "confidence": result.get("confidence", 0.0), "degraded": result["degraded"],
            "matched": result.get("matched_pattern") or "", "unit": result.get("scored_unit", ""),
            "ms": (time.perf_counter() - start) * 1000,
        })
    return pd.concat([frame.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def wilson(successes: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """95% Wilson score interval for a proportion. Small test sets (n < 100) give wide intervals."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(float(max(0.0, centre - half)), 4), round(float(min(1.0, centre + half)), 4)]


def _recall(g: pd.DataFrame) -> Optional[float]:
    a = g[g["label_binary"] == 1]
    return round(float((a["decision"] == "BLOCK").mean()), 3) if len(a) else None


def _fpr(g: pd.DataFrame) -> Optional[float]:
    s = g[g["label_binary"] == 0]
    return round(float((s["decision"] == "BLOCK").mean()), 4) if len(s) else None


def latency_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    pick = lambda q: ordered[min(int(len(ordered) * q), len(ordered) - 1)]
    return {"mean": round(statistics.mean(ordered), 2), "p50": round(pick(0.5), 2), "p95": round(pick(0.95), 2),
            "p99": round(pick(0.99), 2), "max": round(ordered[-1], 2)}


def summarize(run: pd.DataFrame) -> Dict[str, Any]:
    y = run["label_binary"].to_numpy()
    blocked = (run["decision"] == "BLOCK").astype(int).to_numpy()
    flagged = run["decision"].isin(["BLOCK", "ESCALATE"]).astype(int).to_numpy()
    by_regex = (run["reason"] == "regex_match").astype(int).to_numpy()
    by_vector = (run["reason"] == "high_vector_similarity").astype(int).to_numpy()
    out: Dict[str, Any] = {
        "block": binary_metrics(y, blocked, 0.5),
        "block_or_escalate": binary_metrics(y, flagged, 0.5),
        "regex_only_block": binary_metrics(y, by_regex, 0.5),
        "semantic_only_block": binary_metrics(y, by_vector, 0.5),
        "escalate_share_of_safe": round(float(((run["decision"] == "ESCALATE") & (y == 0)).sum() / max((y == 0).sum(), 1)), 4),
        "escalate_share_of_attacks": round(float(((run["decision"] == "ESCALATE") & (y == 1)).sum() / max((y == 1).sum(), 1)), 4),
        "latency_ms": latency_stats(run["ms"].tolist()),
        "degraded_rows": int(run["degraded"].sum()),
    }
    n_attack, n_safe = int((y == 1).sum()), int((y == 0).sum())
    out["confidence_95"] = {
        "block_recall": wilson(int(((blocked == 1) & (y == 1)).sum()), n_attack),
        "block_fpr": wilson(int(((blocked == 1) & (y == 0)).sum()), n_safe),
        "block_or_escalate_recall": wilson(int(((flagged == 1) & (y == 1)).sum()), n_attack),
        "n_attacks": n_attack, "n_safe": n_safe,
    }
    attacks = run[run["label_binary"] == 1]
    out["recall_by_attack_type"] = {t: {"n": int(len(g)), "blocked": round(float((g["decision"] == "BLOCK").mean()), 3),
                                        "block_or_escalate": round(float(g["decision"].isin(["BLOCK", "ESCALATE"]).mean()), 3)}
                                    for t, g in attacks.groupby("attack_type")}
    out["by_language"] = {lang: {"n": int(len(g)), "recall_block": _recall(g), "fpr_block": _fpr(g)}
                          for lang, g in run.groupby("lang") if lang}
    out["by_source"] = {src: {"n": int(len(g)), "recall_block": _recall(g), "fpr_block": _fpr(g)}
                        for src, g in run.groupby("source") if src}
    return out


def examples(run: pd.DataFrame, n: int = 6) -> Dict[str, List[Dict[str, str]]]:
    def pick(mask, k=n):
        part = run[mask].sample(min(k, int(mask.sum())), random_state=0) if mask.any() else run.iloc[0:0]
        return [{"text": r.text[:240], "decision": r.decision, "reason": r.reason, "attack_type": r.attack_type,
                 "nearest_attack": r.matched[:160], "scored_unit": r.unit[:160]} for r in part.itertuples()]
    attack, safe = run["label_binary"] == 1, run["label_binary"] == 0
    return {
        "caught_by_regex": pick(attack & (run["reason"] == "regex_match")),
        "caught_by_semantic": pick(attack & (run["reason"] == "high_vector_similarity")),
        "escalated_attacks": pick(attack & (run["decision"] == "ESCALATE")),
        "missed_attacks": pick(attack & (run["decision"] == "PASS")),
        "false_positives": pick(safe & (run["decision"] == "BLOCK")),
        "escalated_safe": pick(safe & (run["decision"] == "ESCALATE"), 4),
    }


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
def cmd_calibrate(args: argparse.Namespace) -> None:
    layer = Layer1Prefilter(index_dir=args.index)
    if layer.degraded:
        raise SystemExit(f"semantic index not available: {layer.vector_error}")
    sets, sizes = [], {}
    for name, cap in DEV_SETS.items():
        frame = load_set(name)
        texts = frame["text"].tolist()
        attack, margin = unit_arrays(layer, texts)
        sets.append({"name": name, "attack": attack, "margin": margin, "labels": frame["label_binary"].to_numpy(),
                     "regex_hit": regex_blocked(texts), "cap": cap})
        sizes[name] = int(len(frame))
    result = calibrate_multi(sets, args.escalate_budget)
    result["dev_rows"] = sizes
    layer.index.thresholds = Thresholds(
        block_sim=result["block_sim"], block_margin=result["block_margin"], escalate_sim=result["escalate_sim"],
        escalate_margin=0.0, calibrated_on=f"dev sets {sizes}", notes=result)
    layer.index.save_thresholds(args.index)
    print(json.dumps(result, indent=2))
    print(f"[INFO] thresholds written to {os.path.join(args.index, 'thresholds.json')}")


def cmd_report(args: argparse.Namespace) -> None:
    layer = Layer1Prefilter(index_dir=args.index)
    if layer.degraded:
        raise SystemExit(f"semantic index not available: {layer.vector_error}")
    report: Dict[str, Any] = {
        "index": {"dir": os.path.relpath(args.index, BASE_DIR), **{k: layer.index.meta.get(k) for k in
                  ("model", "n_entries", "n_attack", "n_benign", "content_sha256", "git_commit")}},
        "thresholds": layer.index.thresholds.__dict__, "sets": {}, "examples": {},
    }
    for name in args.sets:
        frame = load_set(name)
        run = run_layer(layer, frame)
        report["sets"][name] = summarize(run)
        report["examples"][name] = examples(run)
        s = report["sets"][name]
        b = s["block"]
        print(f"[{name}] n={b['n']} attacks={b['positives']}  BLOCK recall={b['recall']} FPR={b['fpr']} precision={b['precision']}"
              f"  | BLOCK+ESCALATE recall={s['block_or_escalate']['recall']} (safe escalated {s['escalate_share_of_safe']})"
              f"  | p50 {s['latency_ms']['p50']} ms  | 95% CI recall {s['confidence_95']['block_recall']} FPR {s['confidence_95']['block_fpr']}")
    os.makedirs(RESULTS, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
    print(f"[INFO] report written to {args.out}")


def cmd_latency(args: argparse.Namespace) -> None:
    sets = {n: load_set(n) for n in ("test", "external_test")}
    pool = pd.concat([f[f["source"] != "doc_base"] for f in sets.values()])
    chat = pool.sample(min(300, len(pool)), random_state=0)
    docs = sets["test"][sets["test"]["source"] == "doc_base"].sample(100, random_state=0)
    regex = Layer1Prefilter(use_vector=False)
    start = time.perf_counter()
    full = Layer1Prefilter(index_dir=args.index)
    load_s = time.perf_counter() - start
    for _ in range(5):
        full.check("warm up the model with a normal sentence please")
    out: Dict[str, Any] = {"model_and_index_load_seconds": round(load_s, 1), "index_entries": full.index.meta["n_entries"]}
    for label, layer, texts in (("regex_only_chat", regex, chat["text"]), ("full_chat", full, chat["text"]),
                                ("full_document", full, docs["text"])):
        times = []
        for text in texts:
            t = time.perf_counter()
            layer.check(text)
            times.append((time.perf_counter() - t) * 1000)
        out[label] = {"n": len(times), **latency_stats(times), "avg_chars": int(np.mean([len(x) for x in texts]))}
    print(json.dumps(out, indent=2))
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "layer1_latency.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["calibrate", "report", "latency"])
    parser.add_argument("--index", default=DEFAULT_INDEX_DIR)
    parser.add_argument("--data-dir", default=PROCESSED, help="folder holding dataset_v2_{validation,test}.csv (data/processed_public for dataset v3)")
    parser.add_argument("--escalate-budget", type=float, default=0.12)
    parser.add_argument("--sets", nargs="+", default=TEST_SETS)
    parser.add_argument("--out", default=os.path.join(RESULTS, "layer1_eval.json"))
    args = parser.parse_args()
    globals()["PROCESSED"] = os.path.abspath(args.data_dir)   # read by _read_set
    {"calibrate": cmd_calibrate, "report": cmd_report, "latency": cmd_latency}[args.command](args)


if __name__ == "__main__":
    main()
