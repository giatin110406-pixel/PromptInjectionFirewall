# Kết quả kiểm thử (2026-10-14 01:40)

Tổng: **701 qua, 0 lỗi, 1 bỏ qua** (702 test).

| Layer / thành phần | Qua | Lỗi | Bỏ qua | File test |
|---|---:|---:|---:|---|
| API (end-to-end) | 16 | 0 | 0 | test_api.py, test_smoke.py |
| Chất lượng mã nguồn | 72 | 0 | 0 | test_source_hygiene.py |
| Công tắc layer + judge chỉ chạy khi được yêu cầu | 21 | 0 | 0 | test_toggles.py |
| Dữ liệu (dựng dataset, audit, sinh VI) | 109 | 0 | 0 | test_audit_leakage.py, test_bipia_gpt_dataset.py, test_build_dataset_v2.py, test_eda.py, test_generate_vi.py, test_public_only_dataset.py, test_review_vi_test.py, test_validate_vi_test.py |
| L0 Chuẩn hóa | 34 | 0 | 0 | test_normalize.py |
| L1 Chữ ký (chỉ mục + danh mục tình huống) | 121 | 0 | 0 | test_layer1_shipped.py, test_signature_index.py |
| L1 Chữ ký (regex) | 100 | 0 | 0 | test_baseline.py, test_layer1.py, test_layer1_vi_regression.py |
| L1/L2 tiếng Việt (end-to-end) | 19 | 0 | 1 | test_vietnamese_firewall.py |
| L2 Bộ phân loại (chuẩn bị dữ liệu) | 28 | 0 | 0 | test_l2_chunking.py, test_l2_metrics.py |
| L3 LLM judge | 43 | 0 | 0 | test_judge.py |
| L4 Action Firewall | 18 | 0 | 0 | test_action_gate.py, test_layer4.py |
| L5 Output Guard | 33 | 0 | 0 | test_output_guard.py |
| Legacy v1 (XGBoost, không còn trong pipeline) | 11 | 0 | 0 | test_features.py, test_layer2.py |
| Orchestrator (4 quyết định, fail-closed) | 48 | 0 | 0 | test_orchestrator.py, test_types.py |
| Phản hồi (feedback): tổng hợp, hạt giống, kiểm tra lại | 3 | 0 | 0 | test_feedback_report.py |
| Spotlighting + taint | 25 | 0 | 0 | test_spotlight.py |

Test bị bỏ qua: 1 test kiểm tra checkpoint L3 DistilBERT cũ (không nạp được, vocab lệch; L3 DistilBERT đã được thay bằng LLM judge và không còn trong pipeline). Các test dùng model L2 thật tự bỏ qua nếu thiếu artifact (~1,1 GB, không nằm trong git); trên máy này artifact có sẵn nên chúng chạy. Chạy lại: `python PrepareForBCTĐ2/tools/make_test_report.py`.
