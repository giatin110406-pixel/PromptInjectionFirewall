# Kế hoạch triển khai dữ liệu công khai

Ngày lập: 14/10/2026. Danh sách dataset và lý do chọn nằm ở mục 2.5.7 của `BaoCao_Firewall_Layer0_5.docx`. File này mô tả cách đưa các tập đó vào dự án.

## Mục tiêu

Có số đo L1, L2, L3, Spotlighting và L4 trên dữ liệu **không do nhóm hay AI của nhóm tạo ra**, để kiểm tra kết quả hiện tại có còn đúng khi gặp dữ liệu lạ không.

Hướng đề xuất (chưa chốt) là **chỉ đo**: L2 giữ nguyên, dữ liệu mới không vào train hay chọn ngưỡng. Huấn luyện lại L2 là bước 6, chỉ làm khi kết quả đo cho thấy cần.

## Trạng thái thực hiện (cập nhật 14/10/2026)

| Bước | Trạng thái | Ghi chú |
|---|---|---|
| 0. Giấy phép | Xong một phần | `data/raw/public/SOURCES.md`. Tensor Trust không ghi giấy phép; HackAPrompt (gated) và OWASP (401) cần tài khoản Hugging Face |
| 1. Tải về | Xong một phần | 7 nguồn đã tải (20 MB), SHA-256 trong `data/raw/public/hashes.json`. **Chưa tải được HackAPrompt và OWASP** vì máy không có token Hugging Face; không đi vòng qua điều khoản |
| 2. Chuyển định dạng | Xong | `data/scripts/prepare_public_eval.py` → `data/eval/public/*.csv` (13 file). Tensor Trust chỉ còn 910 mẫu sau khi bỏ trùng (kế hoạch ước 2.000 đến 3.000, vì benchmark có nhiều bản trùng) |
| 3. Rò rỉ và trùng | Xong | Chỉ 1 dòng trùng với dữ liệu dự án (multijail_en). Báo cáo: `evaluation/results/public_prepare.json`, `public_leakage_report.json` |
| 4. Đo | Xong | `evaluation/eval_public.py` (L1, L2, pipeline, tài liệu), `eval_public_l3.py` (judge, Haiku thay thế), `eval_public_l4.py` (InjecAgent). Không chỉnh ngưỡng |
| 5. Báo cáo | Xong | `BaoCao_Firewall_Layer0_5_v2.docx` |
| 6. Huấn luyện lại L2 | Không làm | Kế hoạch chỉ làm nếu kết quả đo cho thấy cần; xem phần "Kết quả và khuyến nghị" bên dưới. Quyết định thuộc về nhóm |

Thay đổi so với kế hoạch: thêm Dolly-15k (câu lệnh và đoạn văn bình thường, tiếng Anh) và XQuAD tiếng Việt (câu hỏi và đoạn văn) làm nguồn mẫu bình thường do người viết để đo chặn nhầm, vì plan gốc thiếu phía "bình thường". Phần "mẫu tiếng Việt nhóm tự viết" chưa làm được: cần thành viên nhóm (file mẫu: `data/eval/vi_human_v1_template.csv`).

### Kết quả và khuyến nghị

Số liệu chi tiết nằm ở mục 2.5.7, 4.5, 5.6, 6.6, 7.4, 8.6 của báo cáo. Ba điều đáng chú ý:
1. Tấn công gián tiếp dạng câu trần (InjecAgent base) hầu như không bị phát hiện (14,0% bị bắt, 6,6% làm phiên bị TAINT), nên Layer 4 chỉ giữ được 15,2% hành động tương ứng, trong đó 51 trên 114 ca là do chính sách access_control luôn cần xác nhận. Bản có tiền tố "Ignore all previous instructions" bị bắt 100%.
2. Chặn nhầm trên câu hỏi do người viết (4,0% Dolly, 2,8% XQuAD tiếng Việt) cao hơn trên dữ liệu tự tạo (0,72% dataset_v2 test). Câu dạng "from the passage, extract ..." bị gắn cờ 36 trên 62.
3. deepset chỉ bị bắt 69,2% (khác xa 98,7% trên dataset_v2 test), một phần do cách deepset gán nhãn.

Khuyến nghị: trước khi huấn luyện lại L2, bổ sung mẫu tấn công gián tiếp dạng câu trần và mẫu câu trích xuất bình thường, giữ riêng một tập đo mà không tập nào trong các tập công khai hiện tại được dùng để chọn ngưỡng. Hai tập chưa có (HackAPrompt, OWASP) nên tải trước khi quyết định.

## Bước 0. Xác minh giấy phép và quyền tải

| Tập | Việc cần làm | Đã biết |
|---|---|---|
| Tensor Trust | Đọc notebook và trang tensortrust.ai/paper để tìm giấy phép dữ liệu | Repo GitHub không ghi giấy phép |
| HackAPrompt | Đăng nhập Hugging Face, đồng ý điều khoản của `hackaprompt/hackaprompt-dataset` | MIT, gated |
| OWASP LLM01 V1/V2 | Đồng ý điều khoản; đọc giấy phép "other" | Tải không đăng nhập trả về 401 |
| Gray Swan IPI | Tìm đúng tên tập trên Hugging Face, kích thước và giấy phép | Chưa biết |
| InjecAgent | Không cần | MIT |
| MultiJail | Đọc bài báo để biết bản tiếng Việt do người hay máy dịch | MIT |
| deepset | Không cần | Apache-2.0 |

Tập nào giấy phép không cho dùng trong báo cáo thì bỏ và ghi lại lý do trong mục 2.5.7.

**Hoàn thành khi:** mỗi tập có một dòng ghi giấy phép, đường dẫn nguồn và ngày tải trong `data/raw/public/SOURCES.md`.

## Bước 1. Tải về

- Mỗi tập vào một thư mục riêng: `data/raw/public/<tên tập>/`. Không chạy script nào nằm trong thư mục đã tải.
- Ghi SHA-256 của từng file vào `SOURCES.md` để tái lập.
- Thêm `data/raw/public/` vào `.gitignore` nếu giấy phép không cho phân phối lại.
- HackAPrompt và Tensor Trust lớn (tới hàng trăm nghìn dòng). Chỉ giữ file cần dùng.

## Bước 2. Chuyển về một định dạng chung

Script mới: `data/scripts/prepare_public_eval.py`. Đầu ra mỗi tập là `data/eval/public/<tên tập>.csv`, cùng cột với tập đo hiện có: `text, label_binary, lang, source, attack_type, split`, với `split = public_eval`.

Xử lý riêng từng tập:

| Tập | Lấy gì | Lọc | Dự kiến |
|---|---|---|---|
| Tensor Trust | Benchmark hijacking và extraction đã được tác giả lọc, không dùng bản raw | Bỏ trùng, bỏ câu dưới 20 ký tự | Lấy mẫu 2.000–3.000 (seed 0) |
| HackAPrompt | Cột `user_input` | Bỏ trùng, bỏ câu dưới 20 ký tự; lấy mẫu chia đều theo `level` | khoảng 2.000 |
| deepset | Toàn bộ | Gắn cờ dòng tiếng Đức (`lang = de`) để báo riêng | 662 |
| OWASP V1, V2 | Toàn bộ, giữ cột loại kịch bản | Bỏ dòng trùng giữa V1 và V2 | tối đa 1.200 |
| Gray Swan IPI | Văn bản công cụ hoặc tài liệu có chèn tấn công | Giữ nguyên dạng tài liệu | chưa biết |
| InjecAgent | Phần phản hồi công cụ có chỉ thị của kẻ tấn công, và tên công cụ kẻ tấn công muốn gọi | Xem ghi chú bên dưới | 1.054 ca |
| MultiJail | Cột `vi` | `attack_type = harmful_request` | 315 |
| Mẫu nhóm tự viết | `data/eval/vi_human_v1.csv` | Duyệt chéo bằng `review_vi_test.py` | 50–100 |

**Ghi chú InjecAgent.** Công cụ trong InjecAgent (khóa cửa thông minh, email, ngân hàng...) khác với công cụ CSKH của dự án. Nên dùng theo hai cách:
1. Phản hồi công cụ có chèn chỉ thị: đưa qua đường Spotlighting như một tài liệu không tin cậy, đo tỷ lệ phát hiện.
2. Lệnh gọi công cụ của kẻ tấn công: chỉ đưa vào L4 các ca mà công cụ ánh xạ được sang hành động nhạy cảm của dự án (ví dụ chuyển tiền). Bảng ánh xạ để trong script và ghi số ca dùng được, số ca bị bỏ.

**Ghi chú MultiJail.** Đây là câu hỏi độc hại, không phải prompt injection. Firewall có thể cho qua, và đó là ngoài phạm vi, không phải lỗi. Báo riêng, không gộp vào tỷ lệ bắt tấn công.

**Hoàn thành khi:** mỗi CSV có đúng cột, không dòng rỗng, và script in số dòng theo nhãn và ngôn ngữ.

## Bước 3. Kiểm tra rò rỉ và trùng lặp

1. Chạy `audit_leakage.py` cho từng tập mới: `python data/scripts/audit_leakage.py --offline --csv tensortrust=data/eval/public/tensortrust.csv --csv ...`. Ghi kết quả vào `evaluation/results/public_leakage_report.json`.
2. Kiểm tra trùng với **toàn bộ dữ liệu train của dataset_v2 và chỉ mục L1** (khớp chính xác và gần trùng, như cách đã làm với deepset). Dòng trùng bị loại khỏi tập đo, và số dòng bị loại được ghi lại. Nếu bỏ qua bước này, số đo sẽ lạc quan vì model đã thấy câu đó.
3. Với tập có cả hai nhãn (deepset, OWASP), ghi AUC độ dài và AUC văn phong. Tập nào bị gắn cờ thì vẫn đo, nhưng kết quả phải kèm cảnh báo.

**Hoàn thành khi:** có báo cáo rò rỉ và số dòng còn lại sau khi loại trùng cho từng tập.

## Bước 4. Đo

| Layer | Script | Tập | Chỉ số |
|---|---|---|---|
| L1 | `evaluation/eval_layer1.py` | Tensor Trust, HackAPrompt, deepset, OWASP, MultiJail | Tỷ lệ chặn, chặn nhầm |
| L2 | `evaluation/eval_l2_multilingual.py` (thêm các tập mới vào danh sách `SETS`) | Như trên, cộng mẫu nhóm tự viết | Recall, chặn nhầm, AUC |
| Pipeline L0–L2 | Như trên | Như trên | Quyết định cuối: ALLOW, REVIEW, BLOCK |
| L3 | `PrepareForBCTĐ2/tools/eval_l3_judge.py` | Chỉ các ca có điểm L2 trong khoảng 0,30–0,98 | Đúng, sai, judge nói vô hại với tấn công |
| Spotlighting | `PrepareForBCTĐ2/tools/eval_context_scan.py` | Gray Swan, phần phản hồi công cụ của InjecAgent | Tỷ lệ phát hiện tài liệu có chèn |
| L4 | Test mới trong `tests/` | Ca InjecAgent ánh xạ được | Tỷ lệ hành động bị chặn hoặc đưa REVIEW |

Quy tắc khi đo:
- **Không chỉnh ngưỡng** theo kết quả trên các tập này. Ngưỡng đã chọn trên dev giữ nguyên.
- Báo từng tập riêng, kèm khoảng tin cậy 95% (Wilson), vì nhiều tập nhỏ.
- Tập chỉ có nhãn tấn công thì chỉ báo recall. Chặn nhầm chỉ báo trên tập có câu bình thường.
- Ghi git commit, SHA-256 dữ liệu và ngưỡng đang dùng vào `evaluation/results/public_eval.json`.

**Hoàn thành khi:** có `public_eval.json` và một bảng tổng hợp chạy lại được bằng một lệnh.

## Bước 5. Cập nhật báo cáo

- Mục 2.5.7: thay kích thước thô bằng số dòng thật sau khi lọc, cập nhật giấy phép.
- Mục 12: thêm bảng kết quả trên dữ liệu công khai, đặt cạnh kết quả cũ.
- Mục 13: cập nhật hạn chế theo kết quả, ví dụ loại tấn công nào bị bỏ sót nhiều.
- `docs/ai_use_disclosure_log.md`: ghi việc dùng các tập công khai (không phải AI sinh, nhưng phải khai nguồn).

## Bước 6 (tùy chọn). Huấn luyện lại L2

Chỉ làm nếu bước 4 cho thấy L2 bỏ sót nhiều tấn công do người viết, ví dụ recall trên Tensor Trust hoặc HackAPrompt thấp hơn hẳn recall trên dataset_v2 test.

Nếu làm:
- Chia mỗi tập công khai thành phần train và phần giữ lại để đo. **Phần giữ lại không bao giờ vào train hay chọn ngưỡng.**
- Tensor Trust và HackAPrompt chỉ có nhãn tấn công, nên phải thêm câu bình thường tương ứng để không làm lệch tỷ lệ nhãn. Nếu không có nguồn câu bình thường do người viết, model sẽ học "văn phong tấn công" thay vì nội dung.
- Sau khi huấn luyện lại phải chọn lại nhiệt độ, ngưỡng L2, ngưỡng L1 và kiểm tra lại hai mốc 0,30/0,98 của L3.

## Thứ tự và phụ thuộc

```
Bước 0 (giấy phép) → Bước 1 (tải) → Bước 2 (chuyển định dạng) → Bước 3 (rò rỉ) → Bước 4 (đo) → Bước 5 (báo cáo)
                                                                                    └→ Bước 6 (nếu cần)
Mẫu nhóm tự viết: làm song song, bắt đầu ngay, chỉ cần có trước bước 4.
```

Nên làm trước các tập dễ và rõ giấy phép: deepset, InjecAgent, MultiJail, HackAPrompt. Tensor Trust, OWASP và Gray Swan làm sau khi xác minh xong bước 0.

## Rủi ro

| Rủi ro | Cách xử lý |
|---|---|
| Giấy phép không cho dùng | Bỏ tập đó, ghi lý do |
| Tập công khai trùng với dữ liệu train | Loại dòng trùng ở bước 3 |
| Nhiều câu HackAPrompt là rác hoặc không phải tấn công thật | Lọc ở bước 2; đọc tay 50 câu ngẫu nhiên trước khi đo |
| Câu bình thường quá ít nên chặn nhầm có sai số lớn | Báo khoảng tin cậy; ưu tiên bổ sung mẫu nhóm tự viết |
| InjecAgent không khớp công cụ của dự án | Chỉ đo ca ánh xạ được, ghi rõ số ca bị bỏ |
| Kết quả xấu hơn số đo hiện tại | Đây là mục đích của việc đo. Báo đúng số, không chỉnh ngưỡng để làm đẹp |
