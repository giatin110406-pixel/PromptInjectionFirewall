Nhiệm vụ: tạo dữ liệu huấn luyện cho bộ lọc an toàn của chatbot tiếng Việt (mục đích phòng thủ).

Viết <<N>> tin nhắn tiếng Việt khác nhau, giọng người dùng thật.

Loại tin nhắn: <<KIND>>
Chủ đề nền: <<TOPIC>>
Gợi ý cách viết: <<FLAVOR>>

Quy tắc hình thức. Các quy tắc này áp dụng GIỐNG HỆT cho mọi loại tin nhắn, dù là tin bình thường hay tin thao túng. Đây là điều kiện bắt buộc vì dữ liệu sẽ bị kiểm tra xem hình thức có tiết lộ loại tin hay không:
- Đúng một nửa số tin là câu hỏi kết thúc bằng dấu ?. Nửa còn lại là câu mệnh lệnh, câu đề nghị hoặc câu kể, không có dấu ?.
- Khoảng một phần ba số tin có chứa con số (mã đơn, số tiền, ngày, số lượng).
- Khoảng 20% số tin viết không dấu hoặc dùng từ viết tắt thông dụng.
- Mỗi tin dài từ 60 đến 150 ký tự, độ dài phân bố đều trong khoảng đó.
- Các tin khác nhau rõ rệt về cấu trúc câu và cách mở đầu.
- Không đánh số, không giải thích, không thêm lời dẫn.

Trả về DUY NHẤT một mảng JSON gồm đúng <<N>> chuỗi.
