"""
Exploratory data analysis for dataset v2 (P2-T5).

Writes four SVG charts and a markdown report to evaluation/results/eda/. The charts are drawn
with plain Python (no matplotlib), so the script runs anywhere the project runs. SVG files open
in any browser and can be pasted into a report or slides.

    python evaluation/eda.py
    python evaluation/eda.py --data-dir data/processed --out-dir evaluation/results/eda
"""
import argparse
import math
import os
import sys
from typing import Dict, List, Sequence, Tuple
from xml.sax.saxutils import escape

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data", "processed")
OUT_DIR = os.path.join(BASE_DIR, "evaluation", "results", "eda")
SPLITS = ("train", "validation", "test")
SAFE_COLOR, ATTACK_COLOR = "#2a7ab9", "#c4432b"
FONT = "font-family='Segoe UI, Arial, sans-serif'"


def _svg(width: int, height: int, body: str, title: str) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"<rect width='100%' height='100%' fill='white'/>"
        f"<text x='16' y='26' {FONT} font-size='16' font-weight='600'>{escape(title)}</text>{body}</svg>"
    )


def _legend(names: Sequence[str], colors: Sequence[str], x: int, y: int) -> str:
    out = []
    for i, (name, color) in enumerate(zip(names, colors)):
        out.append(f"<rect x='{x + i * 130}' y='{y}' width='12' height='12' fill='{color}'/>"
                   f"<text x='{x + i * 130 + 18}' y='{y + 11}' {FONT} font-size='12'>{escape(name)}</text>")
    return "".join(out)


def grouped_bars(title: str, categories: Sequence[str], series: Dict[str, Sequence[float]],
                 colors: Sequence[str], width: int = 760) -> str:
    """Horizontal grouped bars: one group per category, one bar per series."""
    names = list(series)
    bar_h, gap, left, top = 16, 14, 190, 70
    group_h = bar_h * len(names) + gap
    height = top + group_h * len(categories) + 20
    peak = max((v for vals in series.values() for v in vals), default=1) or 1
    scale = (width - left - 90) / peak
    body = [_legend(names, colors, left, 38)]
    for i, category in enumerate(categories):
        y = top + i * group_h
        body.append(f"<text x='{left - 8}' y='{y + bar_h}' text-anchor='end' {FONT} font-size='12'>{escape(str(category))}</text>")
        for j, name in enumerate(names):
            value = series[name][i]
            w = max(value * scale, 1 if value else 0)
            by = y + j * bar_h
            body.append(f"<rect x='{left}' y='{by}' width='{w:.1f}' height='{bar_h - 2}' fill='{colors[j]}'/>"
                        f"<text x='{left + w + 6:.1f}' y='{by + bar_h - 4}' {FONT} font-size='11'>{int(value):,}</text>")
    return _svg(width, height, "".join(body), title)


def length_histogram(frame: pd.DataFrame, bins: int = 10, lo: float = 1.0, hi: float = 4.2) -> Tuple[List[str], Dict[str, List[int]]]:
    """Counts per label over log10(length) bins. Log scale because chat rows are ~100 chars and documents ~1,000+."""
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    labels = [f"{int(10 ** edges[i]):,}-{int(10 ** edges[i + 1]):,}" for i in range(bins)]
    logs = frame["text"].astype(str).str.len().clip(lower=1).map(math.log10)
    counts: Dict[str, List[int]] = {}
    for name, value in (("safe", 0), ("attack", 1)):
        part = logs[frame["label_binary"] == value]
        counts[name] = [int(((part >= edges[i]) & (part < edges[i + 1] if i < bins - 1 else part <= edges[i + 1])).sum())
                        for i in range(bins)]
    return labels, counts


def _md_table(frame: pd.DataFrame) -> str:
    """Markdown table without the optional `tabulate` dependency."""
    frame = frame.reset_index()
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    divider = "|" + "|".join("---" for _ in frame.columns) + "|"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider] + body)


def build_report(frame: pd.DataFrame, out_dir: str) -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    charts: Dict[str, str] = {}

    by_split = {name: [int(((frame["split"] == s) & (frame["label_binary"] == v)).sum()) for s in SPLITS]
                for name, v in (("safe", 0), ("attack", 1))}
    charts["01_label_by_split.svg"] = grouped_bars("Labels per split", list(SPLITS), by_split, [SAFE_COLOR, ATTACK_COLOR])

    langs = sorted(frame["lang"].unique())
    by_lang = {name: [int(((frame["lang"] == l) & (frame["label_binary"] == v)).sum()) for l in langs]
               for name, v in (("safe", 0), ("attack", 1))}
    charts["02_language_by_label.svg"] = grouped_bars("Language mix per label", langs, by_lang, [SAFE_COLOR, ATTACK_COLOR])

    attack_counts = frame[frame["label_binary"] == 1]["attack_type"].value_counts()
    charts["03_attack_types.svg"] = grouped_bars(
        "Attack types (attack rows only)", list(attack_counts.index), {"attack": list(attack_counts.values)}, [ATTACK_COLOR])

    labels, counts = length_histogram(frame)
    charts["04_length_by_label.svg"] = grouped_bars(
        "Text length (characters, log bins) per label", labels, counts, [SAFE_COLOR, ATTACK_COLOR])

    for name, svg in charts.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as handle:
            handle.write(svg)

    lengths = frame.assign(chars=frame["text"].astype(str).str.len()).groupby("label_binary")["chars"].describe().round(1)
    markdown = [
        "# EDA: dataset v2", "",
        f"- Rows: {len(frame):,} (safe {int((frame['label_binary'] == 0).sum()):,}, attack {int((frame['label_binary'] == 1).sum()):,})",
        f"- Distinct base texts (`orig_id`): {frame['orig_id'].nunique():,}",
        f"- Distinct attack templates (`template_id`): {frame[frame['template_id'] != '']['template_id'].nunique():,}",
        f"- Synthetic rows: {int(frame['is_synthetic'].sum()):,} of {len(frame):,}", "",
        "## Rows by source and label", "", _md_table(frame.groupby(["source", "label"]).size().unstack(fill_value=0)), "",
        "## Rows by language and label", "", _md_table(frame.groupby(["lang", "label"]).size().unstack(fill_value=0)), "",
        "## Rows by split and label", "", _md_table(frame.groupby(["split", "label"]).size().unstack(fill_value=0)), "",
        "## Attack types", "", _md_table(attack_counts.to_frame("rows")), "",
        "## Variants", "", _md_table(frame.groupby(["variant", "label"]).size().unstack(fill_value=0)), "",
        "## Text length (characters) by label (0 = safe, 1 = attack)", "", _md_table(lengths), "",
        "## Charts", "",
    ] + [f"- ![{name}]({name})" for name in charts]
    with open(os.path.join(out_dir, "eda_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown) + "\n")
    return charts


def load_dataset(data_dir: str) -> pd.DataFrame:
    parts = [pd.read_csv(os.path.join(data_dir, f"dataset_v2_{s}.csv")) for s in SPLITS
             if os.path.exists(os.path.join(data_dir, f"dataset_v2_{s}.csv"))]
    if not parts:
        raise SystemExit(f"No dataset_v2_*.csv in {data_dir}. Run data/scripts/build_dataset_v2.py first.")
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=DATA_DIR)
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()
    charts = build_report(load_dataset(args.data_dir), args.out_dir)
    print(f"[INFO] wrote {len(charts)} charts and eda_report.md to {args.out_dir}")


if __name__ == "__main__":
    main()
