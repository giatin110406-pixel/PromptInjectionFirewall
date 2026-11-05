# Thử file/link và theo dõi kết quả thực thi trong demo local

Mở `http://localhost:3001/demo/`, chọn bối cảnh và **Agent thật**. Groq/Gemini gọi LLM thật; `scripted` là lựa chọn offline với chính sách tool cố định.

## Backend & giao dịch

Bảng bên phải hiển thị tài khoản hoặc tất cả đơn hàng, kể cả đơn chưa refund. Mỗi tài khoản có số dư đầu phiên và thay đổi; mỗi đơn có giá trị, tổng đã hoàn và phần còn lại.

Tab **Nhật ký** có mã biên nhận, thời gian, payload và thay đổi trước → sau. Phân biệt:

| Trạng thái | Ý nghĩa |
|---|---|
| Đã thực thi | Backend xử lý thành công; có trong danh sách `executed`. |
| Thực thi lỗi | Firewall có thể đã ALLOW nhưng backend từ chối, ví dụ thiếu số dư. |
| Chờ duyệt | Lệnh chưa được thực thi. |
| Đã chặn | Firewall từ chối, backend không xử lý lệnh. |
| Đã hủy | Người duyệt hủy lệnh; không thay đổi trạng thái nghiệp vụ. |

Sau khi duyệt, nhật ký giữ lại quyết định duyệt và có biên nhận thực thi riêng nếu backend đã xử lý. Các tài khoản/đơn/giao dịch vẫn là dữ liệu thử trong bộ nhớ, được làm mới khi tạo phiên hoặc đổi bối cảnh. Chế độ **Kịch bản** cũ chỉ kiểm tra quyết định firewall, không thực thi backend của Agent.

## Đính kèm tài liệu

1. Chọn **+ Tài liệu** → **Tải file**, **Link web** hoặc **Dán nội dung**.
2. Có thể tải file mẫu ngay trong tab Tải file, xem/sửa rồi chọn file để đính kèm.
3. Việc đính kèm chỉ nạp dữ liệu, không gọi LLM. Phiên chat, trạng thái và lịch sử giao dịch được giữ nguyên.
4. Gửi yêu cầu đọc/tóm tắt/xử lý trong chat. Agent tự chọn `open_document`, `read_email`, `fetch_url` hoặc `lookup_order`; nội dung được đưa qua `process_context` trước khi trả cho LLM.
5. Mở tab **Tài liệu** để xem nguồn, mã tài liệu, hash, trạng thái đã đọc và toàn bộ văn bản trích xuất. Xem văn bản ở đây không tính là Agent đã đọc.

Các nút **Chạy ca này** của kịch bản mẫu tạo phiên mới để so sánh độc lập. Để thử tài liệu vừa tải trong phiên hiện tại, gửi yêu cầu ở ô chat.

Tên file và URL bên ngoài không được đưa thẳng vào system prompt. System prompt chỉ chứa các mã tài nguyên do server tạo. Nội dung trong file, email, JSON và trang web vẫn là dữ liệu ngoài, không trở thành chỉ dẫn trực tiếp của người dùng.

## Định dạng và giới hạn

- PDF: trích text và chú thích. PDF scan/ảnh chưa có OCR; PDF có mật khẩu cần xuất bản không khóa.
- DOCX: đọc văn bản, text ẩn, tracked deletions, comments, header/footer và footnotes. Không thực thi macro.
- TXT/MD/CSV/JSON: đọc nội dung nguyên bản UTF-8 hoặc UTF-16 có BOM.
- HTML: giữ cả markup/comment/text ẩn cho firewall; không chạy JavaScript.
- EML: đọc header và các phần text/plain, text/html; không giải file nhị phân lồng trong thư.
- Link: tải HTTP/HTTPS ở cổng 80/443, kiểm tra đích mỗi lần chuyển hướng và cố định IP đã kiểm tra. Chỉ tải địa chỉ internet công khai; file trên máy hoặc mạng nội bộ cần upload trực tiếp.
- 5 file/lần, 5 MB/file, 10 MB/lần; 20.000 ký tự/file; tối đa 10 tài liệu và 50.000 ký tự/phiên. Nội dung vượt giới hạn bị từ chối, không tự cắt bỏ phần cuối.

Các file mẫu tại `frontend/security-console/public/attachment-samples` được tạo bởi `evaluation/make_attachment_samples.py`. Phần injection được lấy lại từ kịch bản Shop Mây tổng hợp có sẵn trong `demo_scenarios.json`, gồm HTML comment, EML, DOCX text ẩn và PDF annotation. Đây là dữ liệu demo, không phải kết quả đánh giá trên tài liệu người dùng thật.
