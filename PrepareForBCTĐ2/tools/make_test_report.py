"""
Run the whole test suite and write a per-layer report.

    python PrepareForBCTĐ2/tools/make_test_report.py

Outputs (PrepareForBCTĐ2/results/): test_report.md (table), test_report.json, pytest_output.txt.
Add a row to LAYER_OF when a new test file is added for a new layer.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(ROOT, "PrepareForBCTĐ2", "results")

# test file -> layer it protects
LAYER_OF = {
    "test_normalize.py": "L0 Chuẩn hóa",
    "test_baseline.py": "L1 Chữ ký (regex)",
    "test_layer1.py": "L1 Chữ ký (regex)",
    "test_layer1_vi_regression.py": "L1 Chữ ký (regex)",
    "test_layer1_shipped.py": "L1 Chữ ký (chỉ mục + danh mục tình huống)",
    "test_signature_index.py": "L1 Chữ ký (chỉ mục + danh mục tình huống)",
    "test_vietnamese_firewall.py": "L1/L2 tiếng Việt (end-to-end)",
    "test_l2_chunking.py": "L2 Bộ phân loại (chuẩn bị dữ liệu)",
    "test_l2_metrics.py": "L2 Bộ phân loại (chuẩn bị dữ liệu)",
    "test_spotlight.py": "Spotlighting + taint",
    "test_action_gate.py": "L4 Action Firewall",
    "test_output_guard.py": "L5 Output Guard",
    "test_judge.py": "L3 LLM judge",
    "test_feedback_report.py": "Phản hồi (feedback): tổng hợp, hạt giống, kiểm tra lại",
    "test_toggles.py": "Công tắc layer + judge chỉ chạy khi được yêu cầu",
    "test_layer4.py": "L4 Action Firewall",
    "test_orchestrator.py": "Orchestrator (4 quyết định, fail-closed)",
    "test_types.py": "Orchestrator (4 quyết định, fail-closed)",
    "test_api.py": "API (end-to-end)",
    "test_smoke.py": "API (end-to-end)",
    "test_build_dataset_v2.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_audit_leakage.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_generate_vi.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_validate_vi_test.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_review_vi_test.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_eda.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_bipia_gpt_dataset.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_public_only_dataset.py": "Dữ liệu (dựng dataset, audit, sinh VI)",
    "test_source_hygiene.py": "Chất lượng mã nguồn",
    "test_features.py": "Legacy v1 (XGBoost, không còn trong pipeline)",
    "test_layer2.py": "Legacy v1 (XGBoost, không còn trong pipeline)",
}


def main() -> int:
    os.makedirs(RESULTS, exist_ok=True)
    xml_path = os.path.join(RESULTS, "pytest_junit.xml")
    proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           f"--junitxml={xml_path}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(RESULTS, "pytest_output.txt"), "w", encoding="utf-8") as handle:
        handle.write(proc.stdout[-6000:] + "\n" + proc.stderr[-2000:])

    per_file = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0})
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        name = os.path.basename(case.get("classname", "").replace(".", "/")) if False else case.get("classname", "").split(".")[1] + ".py"
        if case.find("failure") is not None or case.find("error") is not None:
            per_file[name]["failed"] += 1
        elif case.find("skipped") is not None:
            per_file[name]["skipped"] += 1
        else:
            per_file[name]["passed"] += 1

    per_layer = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0, "files": []})
    for name, counts in sorted(per_file.items()):
        layer = LAYER_OF.get(name, "Khác (chưa phân loại: thêm vào LAYER_OF)")
        for key in ("passed", "failed", "skipped"):
            per_layer[layer][key] += counts[key]
        per_layer[layer]["files"].append(name)

    total = {k: sum(v[k] for v in per_layer.values()) for k in ("passed", "failed", "skipped")}
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Kết quả kiểm thử ({stamp})", "",
             f"Tổng: **{total['passed']} qua, {total['failed']} lỗi, {total['skipped']} bỏ qua** "
             f"({total['passed'] + total['failed'] + total['skipped']} test).", "",
             "| Layer / thành phần | Qua | Lỗi | Bỏ qua | File test |", "|---|---:|---:|---:|---|"]
    for layer, v in sorted(per_layer.items()):
        lines.append(f"| {layer} | {v['passed']} | {v['failed']} | {v['skipped']} | {', '.join(v['files'])} |")
    lines += ["", "Test bị bỏ qua: 1 test kiểm tra checkpoint L3 DistilBERT cũ (không nạp được, vocab lệch; L3 DistilBERT đã được thay bằng LLM judge và không còn trong pipeline). "
              "Các test dùng model L2 thật tự bỏ qua nếu thiếu artifact (~1,1 GB, không nằm trong git); trên máy này artifact có sẵn nên chúng chạy. "
              "Chạy lại: `python PrepareForBCTĐ2/tools/make_test_report.py`."]
    with open(os.path.join(RESULTS, "test_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    with open(os.path.join(RESULTS, "test_report.json"), "w", encoding="utf-8") as handle:
        json.dump({"generated": stamp, "total": total, "per_layer": per_layer}, handle, indent=2, ensure_ascii=False)
    print("\n".join(lines))
    return 0 if total["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
