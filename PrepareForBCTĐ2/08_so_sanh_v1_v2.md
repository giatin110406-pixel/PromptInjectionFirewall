# So sánh engine v1 (cũ) và v2 (mới)

Mã và tài liệu của v1 được giữ nguyên tại `legacy_v1/` (bản chụp commit `65e2a02`, xem `legacy_v1/README.md`).

| | v1 | v2 |
|---|---|---|
| Chuẩn hóa | không | **L0**: 7 góc nhìn (ký tự ẩn, bỏ dấu, leetspeak, base64...) |
| L1 | regex + ChromaDB (tiếng Anh) | regex EN/VI có quy tắc + chỉ mục ngữ nghĩa đa ngôn ngữ (3.590 mẫu) |
| L2 | XGBoost trên đặc trưng thủ công | **mDeBERTa** đa ngôn ngữ, quét từng cửa sổ, hiệu chỉnh nhiệt độ |
| L3 | DistilBERT (checkpoint không nạp được, bị che bằng danh sách từ khóa) | LLM judge phân xử hai mép của L2 (lọt sát nút, chặn chưa chắc); lỗi thì không nới lỏng; Gemini/Ollama/Anthropic/OpenAI cấu hình qua `.env` |
| Nội dung không tin cậy | không | **Spotlighting**: làm sạch, quét, bọc, taint phiên |
| Hành động | Pydantic + vai trò | giữ luật cứng + chính sách YAML + taint + hàng REVIEW + tần suất |
| Đầu ra | không | **L5**: canary, bí mật, PII Việt-Anh, rò rỉ qua ảnh/link |
| Quyết định | cho qua / chặn | 4 mức, mức nặng nhất thắng |
| Khi layer lỗi | âm thầm dùng từ khóa, vẫn cho qua | **fail-closed**, báo `degraded` theo từng layer |
| Dữ liệu | nguồn lẫn nhãn (BIPIA độc, GPT-4o-mini sạch); eval không đi qua L2/L3 | cùng văn bản gốc cho cả hai nhãn, chia theo văn bản gốc và mẫu tấn công, công cụ audit rò rỉ |
| Tiếng Việt | gần như không | 1.838 dòng, tập đo riêng 300 + 200 dòng |

## Số đo (cùng điều kiện)
Các số đo cũ của v1 **không dùng để so sánh công bằng** (xem `legacy_v1/README.md`): trong lần đo của v1, 738 mẫu đều dừng ở L1 và L2 xử lý 0 mẫu, nên mức cải thiện F1 +0,025 chỉ là của regex; checkpoint L3 không nạp được; dữ liệu train L3 lẫn nguồn.

Muốn có bảng so sánh có số thật cần chạy v1 và v2 trên **cùng các tập chưa thấy** (test, `vi_test_v1`, external), gọi thẳng L2 và L3 cũ để chúng xử lý mẫu. **Script này chưa viết**; bảng sẽ bổ sung ở đây khi có.

Số của v2 trên các tập đó: xem `04_layer2_classifier.md` (L1, L2, L1 hoặc L2 trên dataset_v2 test, external, vi_test_v1) và `05_spotlighting_taint.md` (đường ngữ cảnh).
