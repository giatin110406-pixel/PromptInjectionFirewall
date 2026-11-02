# Dữ liệu train bổ sung H5

Nguồn: **OpenAI Codex**, dữ liệu tổng hợp theo mẫu, chưa được người kiểm nhãn độc lập. UTF-8, một object JSON mỗi dòng; `label=1` là prompt injection, `label=0` là nội dung sạch. `author` lưu nguồn từng dòng.

| File | Tấn công | Sạch | Cặp | Family |
|---|---:|---:|---:|---:|
| `tool_json.jsonl` | 320 | 320 | 320 | 16 |
| `vi_cskh.jsonl`: CSKH | 240 | 240 | 240 | 24 |
| `vi_cskh.jsonl`: chuyển tiền không dấu/teencode | 120 | 120 | 120 | 12 |

`text` trong bộ tool là chuỗi JSON hợp lệ. Hai dòng cùng `pair_id` có cấu trúc JSON giống nhau, gồm cả trường ghi chú và metadata dịch vụ. Một nửa cặp đặt nội dung trong trường kết quả nghiệp vụ, nửa còn lại trong `diagnostics.message`. Dòng sạch có thể chứa HTML/comment hoặc từ khóa mật khẩu, OTP; đó là đối chứng có chủ đích, không phải lỗi nhãn.

CSKH gồm hoàn tiền, đổi trả, voucher và tài khoản; ba kiểu có dấu, không dấu, teencode. Các cặp giữ cùng chủ đề, kiểu viết và độ dài tương đương. Bộ tiền bạc là nhóm riêng với tiền tố `money_` trong `family`, đã gộp vào cùng file theo yêu cầu.

**Chia tập theo `family`, không chia ngẫu nhiên từng dòng hoặc từng cặp.** Giữ hai nhãn của một cặp, mọi giá trị thay thế và mọi vị trí chèn của cùng family trong một split. `schema_family` và `template_family` là metadata kiểm tra; `family` là khóa chia tập. Không đưa `author`, `label`, `pair_id`, `family`, `schema_family`, `template_family`, `topic`, `style` vào văn bản đầu vào classifier; chỉ dùng `text`.

Số lượng dòng không tương đương số mẫu độc lập: mỗi family có 10 hoặc 20 cặp thay giá trị/vị trí. Chưa ghép vào v3c, chưa huấn luyện hoặc đóng gói Colab. Người nhận cần duyệt nhãn, chia family với các nguồn train khác và kiểm tra rò rỉ lần nữa khi tích hợp. Kiểm tra trùng văn bản trong lần bàn giao không chứng minh độc lập ngữ nghĩa.

Tái tạo: `python data/scripts/build_handoff_content.py`. Kiểm tra: `python evaluation/validate_handoff_content.py`.
