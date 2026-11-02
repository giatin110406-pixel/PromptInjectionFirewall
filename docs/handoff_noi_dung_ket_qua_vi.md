# Kết quả bàn giao nội dung H1–H6

H1–H5: **01/11/2026**; cập nhật H6: **02/11/2026** (Asia/Bangkok). Người thực hiện: **OpenAI Codex**. Phạm vi: các đầu ra trong `docs/handoff_noi_dung_tan_cong_vi.md`; không triển khai toàn bộ WP1–WP11.

**H1, H4, H5, H6 đã có đầu ra và kiểm tra. H2/H3 có bản tổng hợp đủ định dạng/số lượng để thử tích hợp, nhưng chưa đáp ứng yêu cầu dữ liệu người viết/nhóm tự viết.** Mỗi dòng ghi tác giả thật; không được đổi `author` thành tên người để coi như hoàn tất yêu cầu môn học. Nhóm cần tự viết bộ chính thức độc lập trước khi báo cáo số liệu theo tiêu chí đó.

## 1. File đặt đúng đường dẫn

| Hạng mục | File | Nội dung bàn giao |
|---|---|---|
| H1 | `frontend/security-console/lib/demo_scenarios.json` | 9 ca: shop/bank/work, mỗi miền attack/value/legit; 6 ca mới do Codex, giữ nguyên 3 ca hợp lệ của Claude và ghi nguồn |
| H2 — bản tổng hợp | `data/eval/v4/attack_scenarios_vi.jsonl` | 48 ca: 32 có chỉ thị, 16 chỉ có giá trị (33,3%); 12 tool JSON; đủ 7 loại hành động |
| H3 — bản tổng hợp | `data/eval/v4/friction_flows.jsonl` | 96 luồng: 48 VI/48 EN; 48 dev/48 test; user 48, saved 16, content 32 |
| H4 | `evaluation/adaptive_transforms.py` | `variants(text, lang) -> list[str]`, không gọi LLM; có EN/VI, đồng nghĩa, trộn ngôn ngữ theo mẫu, chia đoạn, JSON, lịch sự, bỏ từ mệnh lệnh và mã hóa |
| H5 — tool | `data/raw/handoff/tool_json.jsonl` | 320 tấn công + 320 sạch, 320 cặp, 16 family, 16 khung dịch vụ × 2 vị trí ghi chú |
| H5 — CSKH/tiền bạc | `data/raw/handoff/vi_cskh.jsonl` | 240 tấn công CSKH + 240 sạch; 120 tấn công tiền bạc không dấu/teencode + 120 sạch; tổng 720 dòng, 36 family |
| H6 | `evaluation/eval_v4_adaptive.py` | Vòng tìm kiếm ưu tiên điểm L2 thấp, dùng `Runner.attack_once`, ngân sách 10/50/200; ghép `adaptive` và xuất PNG; xem `docs/handoff_h6_vi.md` |

Tổng H5: **1.360 dòng, 680 cặp**, nhãn cân bằng. Mỗi cặp giữ cùng khung/chủ đề. Các số lượng là dòng/cặp tổng hợp; không đồng nghĩa có 680 mẫu ngữ nghĩa độc lập. Chưa có người kiểm nhãn độc lập.

H3 giữ cả hai ngôn ngữ và các giá trị thay thế của mỗi chủ đề trong cùng split; phần test dùng mẫu diễn đạt riêng với dev. Người nhận đã lưu dùng đúng fixture giả `0451000123456` của `demo_customer`. Bộ này mô tả tác vụ hợp lệ, không đảm bảo model hiện tại luôn cho qua.

H4 trả bản gốc trước, loại trùng, thứ tự ổn định, tối đa 256 biến thể. Hai câu kiểm thử VI/EN đều tạo đủ biến thể cho ngân sách 200. Hàm không cam kết mọi đầu vào đều có 200 cách biến đổi độc lập hoặc giữ nguyên hiệu quả tấn công. Phần đổi ngôn ngữ là thay cụm từ theo bảng, không phải dịch tự do. Các phép thay cụm từ bảo toàn token tài khoản, mã định danh, email và URL; bản mã hóa phải được giải mã mới lấy lại văn bản gốc.

## 2. Kết quả kiểm tra

### Demo H1

Chạy qua **các route FastAPI thật với L1/L2/L4 cục bộ**, bằng `TestClient`; không giả lập quyết định, không bỏ layer, không gọi judge trả phí. Log sự cố, review queue và feedback được chuyển sang thư mục tạm để không ghi đè dữ liệu vận hành. Engine báo healthy. Mỗi ca có một session mới.

| Miền | attack | value: tài liệu → hành động | legit |
|---|---|---|---|
| Shop | REVIEW | ALLOW → REVIEW (exposure) | ALLOW |
| Bank | BLOCK | ALLOW → REVIEW (exposure) | ALLOW |
| Work | BLOCK | ALLOW → REVIEW (exposure) | ALLOW |

**9/9 đạt.** Tin nhắn người dùng của cả 9 ca đều ALLOW; ba tài liệu attack bị SANITIZE và đánh dấu taint. Ba tài liệu value không bị taint; lý do giữ hành động là `exposure`, không phải số tiền lớn hoặc payload sai.

Chi tiết có trace và lý do từng ca: `evaluation/results/handoff/demo_api_check.json`. Đây là kiểm tra API trong cùng tiến trình, **chưa phải kiểm tra thao tác trên trình duyệt**. Khi demo từng ca, bấm **“Phiên mới”** trước khi chuyển ca; giao diện hiện tại giữ trạng thái taint giữa các lần bấm trong cùng phiên.

Cập nhật 02/11: giữ hai câu mở đầu bối cảnh work mà agent tích hợp đã đổi thành “Bạn tóm tắt giúp ticket máy in nhé.” và giữ báo cáo API mới đạt 9/9 của agent đó. Builder đã được đồng bộ với hai sửa đổi này; thử tái tạo H1 trong thư mục tạm cho kết quả giống chính xác file demo hiện tại. Không chạy lại builder lên dữ liệu thật hoặc ghi đè các ca agent đã sửa.

### Nội dung và H4

- `evaluation/results/handoff/content_validation.json`: kiểm tra parse JSON/JSONL, số lượng, ID, tác giả, giá trị đích nguyên văn, payload qua luật cứng, nguồn đích H3, chia dev/test, nhãn cân bằng, cặp đủ hai nhãn, cùng cấu trúc JSON và độ dài cặp CSKH tương đương.
- Kiểm tra trùng văn bản với `transactions_v1.jsonl`, các file trong `data/eval/public/`, `manualCases.js` và giữa H5 với dữ liệu thử mới. Các ca legit H1 có sẵn được giữ nguyên và không tính là nội dung mới trong kiểm tra sao chép.
- Không thấy trùng nguyên văn hoặc trùng câu dài theo phép chuẩn hóa được mô tả trong báo cáo. So TF-IDF ký tự 3–5, ngưỡng 0,7, không có dòng H5 vượt ngưỡng. Đây là kiểm tra trùng văn bản, không chứng minh độc lập ngữ nghĩa.
- `tests/test_adaptive_transforms.py`: **10 test đạt**, gồm thứ tự/ngân sách, loại trùng, JSON, giải mã khôi phục Unicode, giữ nguyên ID/email/URL khi thay cụm từ hoặc bỏ từ mệnh lệnh, dạng kết quả mong muốn và kiểm tra đầu vào.

## 3. Tái tạo và kiểm tra

Tại thư mục gốc dự án (PowerShell, môi trường hiện có):

```powershell
.\.venv\Scripts\python.exe data/scripts/build_handoff_content.py
.\.venv\Scripts\python.exe evaluation/validate_handoff_content.py
.\.venv\Scripts\python.exe evaluation/check_handoff_demo.py
.\.venv\Scripts\python.exe -m pytest tests/test_adaptive_transforms.py -q
```

Builder tái tạo cả H1/H2/H3/H5; không chạy lại sau khi nhóm đã sửa tay dữ liệu nếu chưa lưu bản riêng. H1 giữ các ca legit hiện có trong file; các ca attack/value và những file dữ liệu còn lại được tái tạo từ mẫu trong builder. H2/H3 cần giữ riêng bản tổng hợp trước khi thay bằng bộ do người viết.

Kiểm tra API cần các model/checkpoint và cache embedding hiện có. Script đặt chế độ offline cho Hugging Face, không tự tải model; thiếu model sẽ không được coi là đạt. Công cụ kiểm trùng dùng scikit-learn trong môi trường dự án. Không cần thêm thư viện cho builder/H4.

## 4. Gửi lại Claude / bước tiếp theo theo handoff

1. Đọc hai README: `data/eval/v4/README.md` và `data/raw/handoff/README.md` để giữ đúng nguồn và cách chia family.
2. H1: nạp file JSON đã có vào trang `/demo`; chạy thử bằng trình duyệt, reset session trước mỗi ca. Phần code trang không thay đổi trong đợt này.
3. H2/H3: dùng bản tổng hợp để kiểm tra đường ống; **nhóm tự viết bộ chính thức độc lập** trước khi báo cáo theo yêu cầu môn học. Không diễn giải việc duyệt lại dữ liệu AI là dữ liệu do người viết.
4. H2/H3: agent tích hợp đã bổ sung `evaluation/eval_v4.py` và các báo cáo nền `v4_eval_v3.json`, `v4_eval_v3b.json` sau lần bàn giao 01/11. H6 dùng lại `Runner` này; CLI, cách chạy, kiểm đếm lượt thử và giới hạn diễn giải nằm trong `docs/handoff_h6_vi.md`. Không tạo số liệu ASR giả hoặc gọi dữ liệu tổng hợp là dữ liệu do người viết.
5. H5: duyệt nhãn, chia theo **family** (giữ cả hai dòng của cặp cùng split), kiểm trùng lại với toàn bộ nguồn train khi ghép v3c; chỉ đưa `text` vào classifier. Chưa ghép dataset, train model, đổi model vận hành hay đóng gói Colab.

Đầu ra được đặt trực tiếp vào các đường dẫn dự án. Bản ZIP gốc tại `artifacts/handoff_noi_dung_2026-11-01.zip` lưu H1–H5. Bản cập nhật H1–H6 tại `artifacts/handoff_noi_dung_2026-11-02.zip` giữ nguyên cấu trúc thư mục, kèm code, test, README, bản ghi kết quả và manifest SHA-256. Không có thay đổi nào được commit trong đợt bàn giao này.

## 5. H6 — kết quả cập nhật 02/11

Đã chạy 32 ca có chỉ thị, mỗi ca 200 lượt; tổng **6.400 lượt**. Báo cáo `evaluation/results/v4_eval_v3b.json` đã có object `adaptive`; biểu đồ ở `evaluation/results/v4_adaptive_v3b.png`, lịch sử ở `evaluation/results/v4_adaptive_v3b_checkpoint.json`. H4 + H6 có **20 test đạt**.

Ở ngân sách 200: detector bypass **10/32 (31,25%)**, ASR-action detection **21/28 (75%)**, provenance **0/28 (0%)**. Bốn ca cấp quyền vốn luôn REVIEW không nằm trong mẫu số ASR. Đây là dữ liệu tổng hợp và phép kiểm tra hành động kịch bản hóa, không phải số đo trên agent LLM thật.

**Policy trên đĩa đã được agent tích hợp thay đổi trong lúc đo.** Số liệu được gắn với snapshot lúc bắt đầu có hash khớp chính xác, lưu tại `evaluation/results/handoff/h6_policy_at_start.yaml`; không gán số liệu cũ cho policy mới. Audit `evaluation/results/handoff/h6_validation_v3b.json` xác nhận các tỷ lệ từ lịch sử, không có lượt trùng, nguồn khớp snapshot và các phần báo cáo nền không đổi. Xem `docs/handoff_h6_vi.md` để đọc chi tiết khác biệt policy và lệnh kiểm tra.
