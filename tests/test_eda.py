import os
import xml.etree.ElementTree as ET

import pandas as pd

from evaluation import eda


def _frame():
    rows = []
    for i in range(60):
        label = i % 2
        rows.append({
            "text": "x" * (20 + i * 30), "label_binary": label, "label": "INJECTION" if label else "SAFE",
            "lang": ["en", "vi", "mixed"][i % 3], "source": "doc_base" if i % 4 else "chat_bank",
            "attack_type": "direct_injection" if label else "safe", "orig_id": f"o{i // 2}",
            "template_id": f"t{i}" if label else "", "variant": "clean" if not label else "attack_insert_1",
            "split": ["train", "validation", "test"][i % 3], "is_synthetic": True, "synthetic_kind": "template_injection",
        })
    return pd.DataFrame(rows)


def test_charts_are_valid_svg_and_report_is_written(tmp_path):
    charts = eda.build_report(_frame(), str(tmp_path))
    assert len(charts) == 4
    for name in charts:
        root = ET.parse(os.path.join(tmp_path, name)).getroot()  # raises if the XML is malformed
        assert root.tag.endswith("svg")
    report = (tmp_path / "eda_report.md").read_text(encoding="utf-8")
    assert "# EDA: dataset v2" in report and "Rows: 60" in report


def test_length_histogram_counts_every_row_once():
    frame = _frame()
    labels, counts = eda.length_histogram(frame)
    assert sum(counts["safe"]) == int((frame["label_binary"] == 0).sum())
    assert sum(counts["attack"]) == int((frame["label_binary"] == 1).sum())
    assert len(labels) == 10


def test_grouped_bars_escapes_text_and_handles_empty_values():
    svg = eda.grouped_bars("a < b & c", ["x<y"], {"safe": [0], "attack": [3]}, ["#000", "#111"])
    ET.fromstring(svg)  # must still parse
    assert "&lt;" in svg
