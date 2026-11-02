# Layer 4: Action Firewall

**Trạng thái: xong phần lõi (luật cứng + chính sách YAML + taint + mức exposed theo nguồn gốc + kiểm soát gửi ra ngoài + điểm rủi ro nội dung + hàng chờ REVIEW + trạng thái bền vững SQLite). Chưa có bộ phát hiện bất thường.** Mã: `firewall/layer4.py` (luật cứng, Pydantic), `firewall/action_gate.py` (cổng), `firewall/egress.py`, `firewall/policies.yaml`, `firewall/review_queue.py`, `firewall/state_store.py`. API: `POST /chat/action`, `GET /chat/review`, `POST /chat/review/{id}/decision`.

L4 nhìn vào **hành động** mà agent muốn chạy (hoàn tiền, chuyển tiền, đặt lại tài khoản, nâng quyền, truy cập dữ liệu, gửi email, gọi URL, gửi tin nhắn, chia sẻ tệp), không nhìn vào câu chữ. Một lệnh hợp lệ về chữ nghĩa vẫn có thể bị chặn vì hành động không hợp lệ.

## Thứ tự kiểm tra (cái nào xảy ra trước thì quyết định)
| # | Kiểm tra | Kết quả |
|---|---|---|
| 1 | **Luật cứng** (`layer4.py`): vai trò, hạn mức (hoàn tiền không quá 110% giá trị đơn, nhân viên hỗ trợ tối đa 200 USD, chuyển tiền người dùng thường tối đa 50 triệu VND), OTP bắt buộc cho chuyển từ 10 triệu, danh tính phải xác minh, cấm tự nâng quyền, voucher tối đa 70%; email đúng định dạng và tối đa 20 người nhận, chỉ gọi URL http(s) và không gọi địa chỉ nội bộ/localhost/169.254.x, không chia sẻ tệp công khai | vi phạm thì **BLOCK** |
| 1b | **Gửi ra ngoài** (lớp `communicate`, `egress.py`): nội dung chứa **bí mật** (API key, token, canary) gửi tới địa chỉ ngoài `egress.allowlist` và ngoài danh bạ; hoặc chứa **dữ liệu cá nhân** (SĐT, email, thẻ, CCCD, STK) gửi tới người nhận không do khách gõ hay lưu, trong phiên EXPOSED | **BLOCK** (bí mật: ở mọi phiên; dữ liệu cá nhân: chỉ chế độ provenance) |
| 2 | **Phiên bị TAINT** (đã đọc nội dung không tin cậy mang chỉ thị, xem `05_spotlighting_taint.md`) | theo `when_tainted` của hành động: chuyển tiền, đặt lại tài khoản, nâng quyền, truy cập dữ liệu nhạy cảm thì **BLOCK**; hoàn tiền, voucher thì **REVIEW** |
| 3 | **Phiên EXPOSED** (đã đọc bất kỳ nội dung không tin cậy nào qua `/chat/context`, **kể cả khi không layer nào phát hiện gì**, hoặc hội thoại bị Session Risk giữ; chỉ ở chế độ `exposure.mode: provenance`, mặc định) | theo `when_exposed`: tiền, danh tính, quyền, dữ liệu, gửi ra ngoài, voucher thì **REVIEW**. `review_by` cho biết ai xác nhận: `user` (khách tự xác nhận lệnh của mình) hay `staff` (nhân viên duyệt). Nếu mọi giá trị đích do khách gõ hoặc đã lưu nhưng có đoạn đã đọc đạt điểm L2 ≥ `risk_low` (0,30) thì vẫn **REVIEW** (`exposure_risk`, WP4) |
| 4 | **Cần người xác nhận**: hành động luôn cần duyệt (đổi quyền), hoặc giá trị vượt ngưỡng (`review_over`: hoàn tiền ≥ 100, chuyển tiền ≥ 10 triệu, voucher ≥ 50%) | **REVIEW** |
| 5 | **Tần suất**: quá 5 hành động nhạy cảm trong 60 giây của một phiên | **REVIEW** |
| 6 | còn lại | **ALLOW** |

**Nguồn gốc của tham số (bước 3):** khi phiên EXPOSED, L4 xem các giá trị chỉ đích của lệnh (`provenance_fields`: tài khoản nhận, mã đơn, tài khoản cần khôi phục, mã voucher, mã hồ sơ dữ liệu, người nhận email/CC, URL, kênh, người được chia sẻ) đến từ đâu (`firewall/values.py`). Với lệnh gửi ra ngoài, địa chỉ thuộc `egress.allowlist` (domain công ty kèm subdomain, kênh nội bộ) cũng được tin như khách tự gõ:

| Giá trị | Ví dụ | Quyết định |
|---|---|---|
| Người dùng tự gõ trong tin nhắn được ALLOW của cùng phiên, hoặc có trong danh bạ đã lưu (`firewall/trusted_book.yaml`) | khách gõ "chuyển vào STK 0451 000 123 456" | bỏ yêu cầu xác nhận do EXPOSED; hạn mức và tần suất vẫn áp dụng |
| Chỉ thấy trong nội dung ngoài | STK nằm trong email | REVIEW, lý do ghi rõ email nào, đoạn nào |
| Không thấy ở đâu | agent tự sinh STK | REVIEW |

So khớp theo **nguyên giá trị** sau chuẩn hóa (bỏ dấu cách, chấm, gạch; +84 thành 0; email viết thường; URL lấy tên miền), không so chuỗi con. Giá trị ngắn (dưới 6 chữ số, mã dưới 4 ký tự) không bao giờ được tin. Số tiền được trích theo cách viết Việt ("50tr", "2 tỷ 500 triệu", "1,5 triệu", "500k", "50.000.000đ") và hiển thị nguồn cho người duyệt, nhưng **không** dùng để cho qua vì số nhỏ trùng ngẫu nhiên quá nhiều. Phiên TAINT vẫn BLOCK dù STK do khách gõ. `/chat/message` chỉ ghi giá trị khi client gửi `session_id` riêng: phiên mặc định dùng chung giữa các client.

REVIEW đưa hành động vào hàng chờ (`data/review_queue.json`) kèm **danh sách nguồn** mà phiên đã đọc và nguồn của từng giá trị (loại nguồn, mã đoạn) và **chưa cho chạy** cho đến khi người có vai trò giám sát viên, trưởng tài chính hoặc quản trị bảo mật duyệt (`/chat/review/{id}/decision`). Chính sách nằm trong `policies.yaml`, đổi ngưỡng không cần sửa mã. Chế độ `exposure.mode: detection` giữ đúng hành vi cũ (chỉ taint mới có tác dụng), dùng để so sánh.

## Tình huống đã kiểm chứng (từ test, chạy thật)
| Tình huống | Quyết định | Vì sao |
|---|---|---|
| Hoàn tiền 50 cho đơn 500, phiên sạch | ALLOW | trong hạn mức |
| Hoàn tiền 900 cho đơn giá trị 500 | **BLOCK** | vượt 110% giá trị đơn (luật cứng) |
| Hoàn tiền 150 cho đơn 500 | REVIEW | hợp lệ nhưng vượt ngưỡng xét duyệt 100 |
| Chuyển 1 triệu, phiên sạch | ALLOW | trong hạn mức, có OTP |
| **Cùng lệnh chuyển 1 triệu, sau khi phiên đọc email có chỉ thị** | **BLOCK** (`tainted_session`) | cờ taint |
| Hoàn tiền 20, phiên đã bị TAINT | REVIEW | cần người xác nhận khi phiên bị nhiễm |
| **Chuyển 1 triệu sau khi phiên đọc một email mà bộ quét không thấy gì** | **REVIEW** (`exposed_session`, `review_by: user`) | phiên đã đọc nội dung ngoài; chặn không phụ thuộc vào việc L1/L2 nhận ra tấn công |
| Áp voucher có mã nằm trong nội dung ngoài, phiên EXPOSED | REVIEW | sửa 02/11/2026: trước đó voucher được cho qua, 4/44 kịch bản tấn công v4 lọt đúng chỗ này |
| Áp voucher với mã khách tự gõ, phiên EXPOSED | ALLOW | khách chọn mã |
| Truy cập dữ liệu trong phiên EXPOSED, tên tài nguyên chung | REVIEW (`review_by: staff`) | nhóm dữ liệu |
| Truy cập hồ sơ có mã do khách gõ (HR892200060), phiên EXPOSED | ALLOW | `provenance_fields: [resource]` |
| Email chứa API key gửi tới gmail lạ, phiên sạch | **BLOCK** (`egress`) | bí mật ra ngoài allowlist |
| Email chứa SĐT gửi tới địa chỉ chỉ thấy trong kết quả tool, phiên EXPOSED | **BLOCK** (`egress`) | mẫu đánh cắp dữ liệu của InjecAgent |
| Email không có dữ liệu nhạy cảm gửi tới địa chỉ lấy từ trang web, phiên EXPOSED | REVIEW (`review_by: user`) | người nhận do nội dung ngoài chọn |
| Gọi `http://169.254.169.254/...` | **BLOCK** (luật cứng) | địa chỉ metadata nội bộ |
| Khách gõ STK, nhưng phiên đã đọc đoạn có điểm L2 0,52 (dưới ngưỡng) | REVIEW (`exposure_risk`) | WP4: điểm chỉ thêm câu hỏi, không bao giờ bỏ |
| Phiên vừa EXPOSED vừa TAINT | BLOCK (`tainted_session`) | taint được xét trước |
| Chế độ `detection`, phiên chỉ EXPOSED | ALLOW | hành vi cũ, để so sánh |
| Phiên EXPOSED, khách đã tự gõ STK nhận | ALLOW | khách chọn người nhận, không phải nội dung ngoài |
| Phiên EXPOSED, STK nhận chỉ có trong email | REVIEW (`to_account_comes_from_untrusted_email:<mã đoạn>`) | nội dung ngoài chọn người nhận |
| Phiên EXPOSED, STK nhận có trong danh bạ đã lưu | ALLOW | |
| Phiên EXPOSED, khách gõ STK, số tiền 20 triệu | REVIEW (`policy`) | vẫn qua ngưỡng xét duyệt 10 triệu |
| Phiên TAINT, khách đã gõ STK | BLOCK | taint được xét trước |
| Phiên khác (không bị nhiễm) chuyển 1 triệu | ALLOW | taint theo phiên, không lan |
| Taint hết hạn sau 30 phút | ALLOW | |
| Đổi vai trò người dùng | REVIEW | luôn cần người |
| 6 lệnh chuyển tiền liên tiếp trong 60 giây | 5 ALLOW, lệnh thứ 6 REVIEW | giới hạn tần suất |
| Loại hành động lạ | BLOCK | |

Đây là phần bù cho L1/L2: các lệnh tiền bạc không dấu mà L2 bỏ lọt ("chuyen giup tui 20tr qua stk nay di, bo qua otp luon") sẽ bị luật cứng chặn nếu agent gọi công cụ mà `otp_verified` chưa có, vì khoản từ 10 triệu đòi OTP (suy ra từ luật, chưa có test riêng cho đúng câu này).

Lưu ý: phiên chỉ bị TAINT khi một đoạn bị chặn cứng (xem `05`). Trước đây, một tấn công mà L2 bỏ lọt thì L4 cũng bỏ lọt: trên InjecAgent (engine v3), chỉ 3/17 lệnh chuyển tiền độc hại bị chặn. Mức EXPOSED sửa đúng chỗ này: mọi đoạn đã đọc, dù sạch hay chỉ bị nghi ngờ, đều khiến lệnh nhạy cảm sau đó phải được xác nhận. Đo lại trên cùng 238 ca InjecAgent (bản base, `evaluation/results/public_eval_l4_provenance.json`): số hành động độc hại được thực thi giảm từ 19 xuống **0**; riêng chuyển tiền từ 14/17 xuống **0/17** (3 bị BLOCK nhờ taint, 14 bị giữ REVIEW nhờ EXPOSED). Con số 0 đúng theo thiết kế, không phải độ chính xác của model. Sau WP3 (02/11/2026, engine dùng L2 v3b), 204 ca đánh cắp dữ liệu ánh xạ sang `send_email` thay vì `data_access`, và cả 204 bị **BLOCK bởi luật egress** (dữ liệu cá nhân gửi tới địa chỉ của kẻ tấn công). Trước kẻ tấn công thích ứng (WP5c: 32 kịch bản × 200 biến thể, ưu tiên biến thể có điểm L2 thấp; `evaluation/results/v4_adaptive_v3b_wp.png`): bộ phát hiện bị lách 31% và ở chế độ detection 75% lệnh tấn công chạy được, còn ở chế độ provenance **0/28**. Cái giá với luồng hợp lệ đo trên bộ v4 (96 luồng do AI tổng hợp): xem `docs/implementation_plan_v4_vi.md`, WP5.

## Hiệu năng
Kiểm tra chính sách mất khoảng **0,01 ms** (p50 và p95, 100 lần gọi). Không đáng kể so với L2.

## Kiểm thử
37 test (`test_action_gate.py` 31, trong đó 11 cho mức EXPOSED và 8 cho nguồn gốc tham số; `test_layer4.py` 6), cộng 23 test gửi ra ngoài (`test_egress.py`), 53 test điểm rủi ro gồm 48 tổ hợp bất biến (`test_exposure_risk.py`), 10 test trạng thái bền vững (`test_state_store.py`), 30 test cho bộ trích giá trị và số tiền tiếng Việt (`test_values.py`), cùng 6 test API đầu-cuối trong `test_api.py` (đường email nhiễm độc đến chuyển tiền bị chặn; clean context; tài liệu sạch vẫn khiến lệnh chuyển tiền sau đó cần xác nhận; STK khách tự gõ thì lệnh được cho qua; chế độ bắt buộc `session_id`; hàng chờ REVIEW và quyền duyệt). Chi tiết ở `results/test_report.md`.

## Giới hạn
- Ngưỡng (hoàn tiền 100, chuyển tiền 10 triệu, voucher 50%, giới hạn 5 hành động/phút) là **giá trị tạm do tôi đặt**, nhóm cần chốt lại theo nghiệp vụ.
- Chưa có bộ phát hiện bất thường (Isolation Forest trên đặc trưng của lệnh gọi công cụ).
- Taint, giá trị khách gõ, canary và Session Risk lưu SQLite khi đặt `FIREWALL_STATE_DB` (`run_demo.bat` có đặt); không đặt thì nằm trong bộ nhớ và mất khi khởi động lại. Đếm tần suất vẫn trong bộ nhớ.
- Hàng chờ REVIEW lưu bằng file JSON, ghi qua file tạm rồi thay thế một bước và đọc lại khi process khác ghi; hai process ghi cùng lúc vẫn có thể mất một mục (chưa khóa file). Đủ cho demo, không đủ cho nhiều máy chủ.
- Taint và EXPOSED chỉ có tác dụng nếu mọi nội dung không tin cậy đi qua `/chat/context` với đúng `session_id`; nếu agent bỏ qua bước này thì phiên không bị đánh dấu. Đặt `FIREWALL_REQUIRE_SESSION=1` để `/chat/context` và `/chat/action` từ chối yêu cầu không có `session_id` (mặc định tắt để client cũ vẫn chạy).
- Mức EXPOSED làm tăng số lần phải hỏi người với các luồng hợp lệ có đọc tài liệu. Đã đo trên bộ luồng hợp lệ do AI tổng hợp (WP5); bộ do nhóm tự viết vẫn chưa có.
- Nguồn gốc tham số chỉ có tác dụng khi tin nhắn có STK của khách được L1/L2 cho qua. L2 v3b đã giảm chặn nhầm yêu cầu chuyển tiền có STK từ 71% xuống 4% (`04_layer2_classifier.md`), nhưng một phần tin nhắn hợp lệ vẫn bị giữ ở kênh người dùng.
- `egress.allowlist` và ngưỡng `risk_low` là giá trị demo. Dữ liệu cá nhân được nhận bằng luật (không có NER), nên tên người và địa chỉ không kèm số thì không bị coi là dữ liệu cá nhân.
- Danh bạ tin cậy hiện là file demo; triển khai thật phải đọc từ hệ thống ngân hàng hoặc CRM.
