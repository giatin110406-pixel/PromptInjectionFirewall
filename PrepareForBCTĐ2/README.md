# PrepareForBCTĐ2: tài liệu cho báo cáo tiến độ lần 2

Tập hợp các báo cáo, số đo, sơ đồ của engine v2. Mỗi layer xong sẽ được bổ sung vào đây (xem mục "Quy ước cập nhật").

## Trạng thái các layer

| Thành phần | Trạng thái | Báo cáo |
|---|---|---|
| Dữ liệu cho L0/L1/L2 (tên, kích thước, nguồn) | xong | [01_datasets.md](01_datasets.md) |
| L0 Chuẩn hóa | xong | [02_layer0_normalize.md](02_layer0_normalize.md) |
| L1 Chữ ký (regex + chỉ mục ngữ nghĩa) | xong | [03_layer1_signatures.md](03_layer1_signatures.md) |
| L2 Bộ phân loại mDeBERTa | chạy được, nối vào pipeline; chặn nhầm tiếng Việt còn 7,8% | [04_layer2_classifier.md](04_layer2_classifier.md) |
| Spotlighting + Taint | xong lõi, đã đo | [05_spotlighting_taint.md](05_spotlighting_taint.md) |
| L4 Action Firewall | xong lõi, chưa có bộ phát hiện bất thường | [06_layer4_action_firewall.md](06_layer4_action_firewall.md) |
| L5 Output Guard | xong, đã đo | [09_layer5_output_guard.md](09_layer5_output_guard.md) |
| L3 LLM judge | code xong; hiện dùng DeepSeek chỉ khi bấm thủ công trên console (Gemini hết hạn mức); số đo là của judge thay thế (Haiku) | [10_layer3_judge.md](10_layer3_judge.md) |
| Security Console v2 | xong, đã chạy thật và chụp ảnh | [11_security_console.md](11_security_console.md) |
| Bộ ca thử thủ công (38 ca: tin nhắn, indirect, hành động, đầu ra) | xong, có kết quả thực tế | [12_bo_prompt_thu_thu_cong.md](12_bo_prompt_thu_thu_cong.md) |
| Giảm chặn nhầm: chính sách đồng thuận, chỉ TAINT khi chắc, vòng phản hồi | xong phần code, đã đo; chưa làm vòng dữ liệu 3 | [13_giam_chan_nham.md](13_giam_chan_nham.md) |
| Đối chiếu file Word với dự án (kiểm số liệu dữ liệu từng con số) | xong; file Word chưa sửa | [14_doi_chieu_bao_cao_word.md](14_doi_chieu_bao_cao_word.md) |
| Demo agent (người dùng giả lập gõ prompt, agent trả lời) | chưa làm | (sẽ bổ sung) |
| Sơ đồ luồng xử lý | xong | [07_workflow.md](07_workflow.md) |
| So sánh v1 và v2 | khung xong, thiếu bảng số đo chung | [08_so_sanh_v1_v2.md](08_so_sanh_v1_v2.md) |

Kết quả kiểm thử toàn bộ: [results/test_report.md](results/test_report.md).

## Cấu trúc
```
PrepareForBCTĐ2/
  README.md                  file này
  01..08_*.md                báo cáo từng phần
  workflow/                  sơ đồ: firewall_workflow.png / .svg / .mmd
  screenshots/               ảnh chụp Security Console (đăng nhập, tổng quan, sự cố, chi tiết, hàng chờ, phòng thử)
  results/                   số đo gốc (JSON), báo cáo test, bảng dữ liệu, độ trễ
  tools/                     mã sinh ra các file trên
```

## Chạy lại (từ thư mục gốc dự án)
```
python PrepareForBCTĐ2/tools/make_test_report.py        # toàn bộ test, theo từng layer  -> results/test_report.md
python PrepareForBCTĐ2/tools/dataset_stats.py           # kích thước dữ liệu             -> results/datasets_summary.md
python PrepareForBCTĐ2/tools/measure_latency.py --tag gpu --device cuda
python PrepareForBCTĐ2/tools/measure_latency.py --tag cpu --device cpu
python PrepareForBCTĐ2/tools/eval_context_scan.py       # đường ngữ cảnh               -> results/context_scan_eval.json
python PrepareForBCTĐ2/tools/run_manual_cases.py       # bộ ca thử thủ công          -> 12_bo_prompt_thu_thu_cong.md
python PrepareForBCTĐ2/tools/eval_soft_block.py         # chính sách đồng thuận (từ l3/records.jsonl) -> results/soft_block_eval.json
python data/scripts/feedback_report.py [--export] [--recheck]   # tổng hợp phản hồi từ console
python PrepareForBCTĐ2/tools/eval_output_guard.py       # L5                           -> results/output_guard_eval.json
python PrepareForBCTĐ2/tools/l2_doc_scores.py           # điểm L2 từng văn bản         -> results/l2_doc_scores.csv
python PrepareForBCTĐ2/tools/eval_l3_judge.py prepare   # L3: ghi prompt judge (rồi cho judge trả lời, xem docstring)
python PrepareForBCTĐ2/tools/eval_l3_judge.py score     # L3 -> results/l3/l3_eval.json
python PrepareForBCTĐ2/tools/draw_workflow.py           # vẽ lại sơ đồ
python evaluation/eval_layer1.py report                 # L1 -> evaluation/results/layer1_eval.json (copy vào results/)
python evaluation/eval_l2_multilingual.py               # L2 -> evaluation/results/l2_eval.json (copy vào results/)
```
Cần artifact L2 (~1,1 GB, không nằm trong git) tại `models/l2_multilingual/artifacts/`.

## Quy ước cập nhật (mỗi layer xong)
1. Viết hoặc cập nhật `NN_layerX_*.md` theo khung: làm gì, đo (có khoảng tin cậy), tình huống chặn và không chặn, hiệu năng, kiểm thử, giới hạn.
2. Chạy lại `make_test_report.py`, `measure_latency.py`, `dataset_stats.py`; thêm file test mới vào bảng `LAYER_OF` trong `make_test_report.py`.
3. Đổi trạng thái khối trong `STATUS` của `tools/draw_workflow.py`, chạy lại.
4. Cập nhật bảng trạng thái ở trên.

## Điều cần nói thẳng khi báo cáo
- Phần tiếng Việt của dữ liệu hầu hết do AI sinh; dữ liệu seed và `vi_test_v1` do Claude viết, nhóm chưa kiểm chéo.
- Số đo trên `vi_test_v1` và external dựa trên tập nhỏ, khoảng tin cậy rộng.
- L1 và L2 cùng thấy phần train nên không độc lập về dữ liệu.
- Các số của engine v1 không dùng được làm cơ sở so sánh công bằng (xem `08_so_sanh_v1_v2.md`).
- Ghi nhận sử dụng AI: `docs/ai_use_disclosure_log.md`.
