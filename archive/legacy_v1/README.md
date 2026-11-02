# Engine v1 (kiến trúc cũ), lưu để so sánh trong báo cáo tiến độ 2

Thư mục này là **bản chụp nguyên trạng** của engine trước khi làm lại, lấy từ commit `65e2a02`
(`feat: integrate Vietnamese firewall agent and multi-layer optimizations`). Không file nào ở engine hiện tại
bị xóa hay sửa vì việc này. Mã trong `legacy_v1/` **không chạy trong API hiện tại**, chỉ để tham chiếu và để
chạy lại khi cần đo so sánh.

Bản gốc `README.md` của dự án lúc đó nằm ở `README_v1_original.md`.

## Pipeline v1

```
Prompt -> L1 (regex + ChromaDB, all-MiniLM-L6-v2)
       -> L2 (XGBoost, đặc trưng thủ công)      \  chỉ chạy ca lưng chừng
       -> L3 (DistilBERT fine-tune)             /
Hành động agent -> L4 (Pydantic policy validator)
Quyết định: cho qua / chặn
```

## Bản đồ file

| Thành phần | Trong `legacy_v1/` | Ở engine hiện tại (v2) |
|---|---|---|
| L1 regex + ChromaDB | `firewall/layer1.py`, `firewall/baseline.py`, `models/layer1_prefilter/build_vector_db.py`, `data/chroma_db/` | `firewall/layer1.py`, `signature_index.py`, `models/layer1_prefilter/build_index.py` (ChromaDB đã bỏ) |
| L2 XGBoost | `firewall/layer2.py`, `models/layer2_xgboost/` (kèm `model.pkl`) | `models/l2_multilingual/` (mDeBERTa, đang train) |
| L3 DistilBERT | `firewall/layer3.py`, `models/layer3_distilbert/` (kèm `checkpoint/model.safetensors`, không commit) | LLM judge (kế hoạch) |
| L4 policy | `firewall/layer4.py` | `firewall/layer4.py` (giữ, sẽ mở rộng) |
| Điều phối | `firewall/orchestrator.py` | `firewall/orchestrator.py` (4 quyết định, fail-closed) |
| Dữ liệu và script | `data/scripts/` | `data/scripts/` (dataset v2, audit leak) |
| Đánh giá | `evaluation/` (kèm kết quả cũ trong `evaluation/results/`) | `evaluation/eval_layer1.py`, `evaluation/results/` |
| Tài liệu | `docs/` (báo cáo production readiness, handoff, kiến trúc cũ...) | `docs/engine_architecture_vi.md`, `docs/layer0_layer1_report_vi.md` |
| Test | `tests/` | `tests/` |

## Những điều cần biết khi dùng v1 làm đối chứng

Các số đo cũ **không dùng được làm cơ sở so sánh công bằng**, vì sao:

- `evaluation/results/layer2_comparison.json` ghi `layer1_stopped_count = 738`, `layer2_handled_count = 0`:
  trong lần đo đó toàn bộ 738 mẫu dừng ở L1 và **L2 không xử lý mẫu nào**. Cải thiện F1 +0,025 là của regex,
  không phải của phần AI.
- `evaluation/results/latency_benchmark.json` (pipeline 0,015 ms) cũng chỉ đo đường đi nhanh, chưa gồm L3.
- Dữ liệu train L3 bị lẫn nguồn (BIPIA là độc, GPT-4o-mini là an toàn), model có thể học nguồn thay vì nội dung.
  Chi tiết ở `evaluation/` của v2 (`leakage_report.json`) và `docs/data_audit_report.md`.
- Checkpoint L3 trong commit này không nạp được (vocab không khớp) và bản v1 che điều đó bằng danh sách từ khóa.
  Vì vậy không có số đo L3 hợp lệ.

Muốn so sánh thật: chạy **cả v1 và v2 trên cùng một tập chưa thấy** (`data/processed/dataset_v2_test.csv`,
`data/eval/vi_test_v1.csv`, `data/eval/tmdeptrai_external_test.csv`) bằng một script đánh giá. Script này
chưa được viết. Với v1, cần chạy L2 và L3 trực tiếp (không qua L1) để chúng thực sự xử lý mẫu.

## Chạy lại v1 (nếu cần)

Mã v1 import `firewall.*`, nên chạy từ trong thư mục này để không lẫn với v2:

```
cd legacy_v1
set PYTHONPATH=.        (Windows cmd)    # hoặc: $env:PYTHONPATH="."  (PowerShell)
python -m pytest tests
```

Cần model: `models/layer2_xgboost/model.pkl` (có sẵn) và `models/layer3_distilbert/checkpoint/` (đã chép kèm
trọng số; file 259 MB bị `.gitignore`, chỉ tồn tại trên máy đã tạo thư mục này).
