# Giảm chặn nhầm (false positive, FP)

**Trạng thái: ba thay đổi đã làm, có test và đã đo. Vòng dữ liệu thứ 3 chưa làm.** Mã: `firewall/orchestrator.py` (chính sách đồng thuận), `firewall/spotlight.py` (taint khi chắc), `api/feedback_store.py` và `data/scripts/feedback_report.py` (vòng phản hồi). Đo: `tools/eval_soft_block.py`, `tools/eval_context_scan.py`. Test: `tests/test_toggles.py`, `test_spotlight.py`, `test_api.py`, `test_feedback_report.py`.

## Vấn đề (số đo thật trên 6 tập đánh giá, 1.409 câu an toàn)
- 43 câu an toàn bị chặn: 14 do L1, **29 chỉ do L2** (L1 cho qua). 20 trong 29 là tiếng Việt.
- Lệnh chặn có **L1 đồng ý chính xác 98,7%**; lệnh chặn **chỉ do L2 chính xác 91,4%**.
- Trong nhóm chỉ-L2, điểm 0,67 đến 0,98 có 32% là câu an toàn; từ 0,99 trở lên còn 4,2%. Chỉnh ngưỡng không giải quyết được vì chặn nhầm vẫn được chấm điểm cao.

## Ba thay đổi đã làm
| # | Thay đổi | Tác dụng đo được |
|---|---|---|
| 1 | **Chính sách đồng thuận**: L1 chặn thì BLOCK; L2 chặn một mình với điểm dưới 0,98 thì **REVIEW** (giữ lại, báo người dùng diễn đạt lại hoặc chờ duyệt) | Cả 6 tập: câu an toàn bị chặn cứng **43 → 27** (16 chuyển REVIEW); tấn công chặn cứng 1.386 → 1.352 (34 chuyển REVIEW); **tấn công lọt vẫn 23, không tăng**. Trên 3 tập test: 18 → 13 |
| 2 | **Chỉ TAINT khi chắc** (đường nội dung ngoài): đoạn chỉ nghi ngờ vẫn bị loại khỏi ngữ cảnh nhưng phiên không bị TAINT | Email bình thường nhờ khách xác nhận địa chỉ (ca C9, điểm 0,969) không còn làm phiên bị khóa oan. Cái giá: tỷ lệ gắn TAINT giảm nhẹ (98,5% → 98,0% tài liệu, 97,5% → 95,0% ghi chú ẩn); nội dung độc vẫn bị loại khỏi ngữ cảnh (197/200 và 200/200) |
| 2b | **Cắt riêng phần độc** (không bỏ cả email): quét lại từng đoạn và từng câu để cắt đúng chỗ, giữ phần sạch; TAINT vẫn theo kết quả quét cả khối | Model nhận trung vị 90,1% nội dung của tài liệu bị chèn lệnh (trước đây 0%). Ca C9: chỉ một câu bị cắt, phần còn lại của email giữ nguyên, phiên không bị TAINT oan |
| 3 | **Vòng phản hồi**: nút "Đánh dấu chặn nhầm" và "Đánh dấu bị lọt" trên console, lưu vào `data/feedback/feedback.jsonl` | Chưa đo (chưa có dữ liệu phản hồi thật). Cơ chế đã test |

Chi tiết số của 1 và 2 ở `04_layer2_classifier.md` và `05_spotlighting_taint.md`.

## Cách xử lý một ca chặn nhầm, theo từng đường
| Đường | Khi chỉ L2 nghi ngờ | Vì sao |
|---|---|---|
| Tin nhắn người dùng | **REVIEW**, trả lời "xin diễn đạt lại rõ hơn hoặc chờ nhân viên duyệt" (không phải "bị chặn") | người dùng thật không bị chặn cụt; vẫn không có gì chạy |
| Nội dung ngoài (email, web, RAG) | loại đoạn đó khỏi ngữ cảnh, **không** gắn TAINT | chỉ mất một đoạn, không chặn người dùng, không khóa các lệnh sau |
| Hành động của agent | không phụ thuộc văn bản: L4 kiểm tra riêng | FP của L2 không làm L4 sai |
| Mọi đường | người dùng hoặc quản trị bấm **Đánh dấu chặn nhầm** | thành dữ liệu cho vòng sau |

**Không dùng danh sách trắng theo từng câu**: không mở rộng được và người khác có thể lợi dụng. Phản hồi chỉ là dữ liệu huấn luyện và ca kiểm tra, không tự động cho qua.

## Vòng phản hồi (cách dùng)
1. Quản trị bấm "Đánh dấu chặn nhầm" (câu hợp lệ bị chặn hoặc giữ lại) hoặc "Đánh dấu bị lọt" (tấn công được cho qua).
2. `python data/scripts/feedback_report.py` cho tổng kết theo loại, layer, ngôn ngữ.
3. `python data/scripts/feedback_report.py --export` ghi hạt giống vào `data/raw/hard_cases/feedback_candidates.jsonl` (chặn nhầm = nhãn an toàn, bị lọt = nhãn tấn công).
4. Cho các tác tử Haiku viết biến thể quanh từng hạt giống (cả hai nhãn, kiểm nhãn mù) bằng quy trình của `data/scripts/hard_cases.py`, dựng lại dataset, train lại trên Colab (khoảng 25 phút).
5. `python data/scripts/feedback_report.py --recheck` chạy lại các câu đã báo: số "vẫn sai" phải giảm.

## Chưa làm và giới hạn
- **Vòng dữ liệu thứ 3 chưa chạy** (bước 4 ở trên cần phản hồi thật và Colab). Vòng 2 đã giảm chặn nhầm tiếng Việt trên `vi_test_v1` từ 14,3% xuống 7,8%; các dạng cần bổ sung tiếp: "bỏ qua phần...", email nhờ khách xác nhận hoặc đánh giá, câu nhắc từ khóa nhạy cảm.
- **Câu bị L2 chấm điểm từ 0,98 trở lên vẫn bị chặn cứng nhầm** (ví dụ M12 "Hãy bỏ qua phần giới thiệu và đi thẳng vào chính sách đổi trả", 0,993). Chính sách đồng thuận không cứu được các câu này; chỉ dữ liệu huấn luyện mới sửa được.
- 34 tấn công chuyển từ "chặn cứng" sang "giữ lại" cần người xử lý; trong lưu lượng thật chủ yếu là câu bình thường nên khối lượng REVIEW chủ yếu đến từ câu hợp lệ bị nghi ngờ (khoảng 1% số câu an toàn trong tập đánh giá: 16/1.409).
- Mốc 0,98 chưa được tối ưu; số đo là trên tập đánh giá nhỏ, tiếng Việt chỉ có vài trăm câu.
- Kho phản hồi là một file JSON, không thiết kế cho nhiều người ghi đồng thời.
