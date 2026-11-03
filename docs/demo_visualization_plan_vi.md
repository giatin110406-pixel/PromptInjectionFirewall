# Kế hoạch hoàn thiện demo Firewall

Ngày: 03/11/2026

## Mục tiêu

Người xem có thể theo dõi một yêu cầu thật đang đi qua từng lớp, hiểu lớp đó kiểm tra điều gì, đọc lý do/quyết định thực tế, và phân biệt rõ firewall chặn với lỗi hoặc giới hạn quota của LLM. Bản demo vẫn giữ trải nghiệm chat, chọn bối cảnh và thử tệp.

## Kế hoạch

1. **Bản đồ pipeline nổi bật** — đưa sơ đồ L0–L4, Power Agent và trạng thái L5 lên đầu trang demo; hiển thị lớp đang xử lý, thời gian, trạng thái và mũi tên luồng.
2. **Tiến trình từ backend** — phát sự kiện khi mỗi lớp bắt đầu/kết thúc; UI nhận cập nhật trong khi request đang chạy. Không tự dựng các bước không có trong trace.
3. **Giải thích tại từng lớp** — click lớp để xem cách xử lý, score/ngưỡng, model/Judge, lý do, tool và dữ liệu nguồn; giữ các lần chạy lặp theo đúng thứ tự.
4. **Phát lại các trace đã lưu** — cung cấp mẫu benign bị L2 gắn cờ rồi Judge cho qua, mẫu chữ ký bị chặn, mẫu L4 yêu cầu duyệt, và lỗi quota. Ghi rõ đây là bản ghi lưu sẵn, không gọi LLM hay thực hiện hành động.
5. **Trạng thái trung thực** — phân biệt ALLOW, nghi ngờ, REVIEW, BLOCK, lỗi LLM và lớp chưa chạy. L5 được gắn “chưa tích hợp vào vòng lặp Agent”.
6. **Chống treo khi LLM chậm/hết quota** — giới hạn thời gian, không ngủ chờ retry 429, giải phóng nút gửi và hiện thông báo tiếng Việt có thể hiểu được.
7. **Hoàn thiện giao diện** — đồng bộ card, khoảng cách, màu, responsive, bàn phím và hỗ trợ reduced-motion; không che khuất chat trên màn hình nhỏ.
8. **Đóng gói và phát hành** — chạy test offline và build frontend; publish bản đọc trace trên hosting riêng tư. Chat Agent trực tiếp chỉ bật khi có backend HTTPS được triển khai riêng và cấu hình đúng; không đưa key hoặc endpoint localhost lên hosting.

## Tiêu chí nghiệm thu

- Trace thực tế cập nhật theo thời gian và giữ nguyên quyết định của từng lớp.
- Có thể chọn mẫu, phát/tạm dừng, bước tới/lùi và mở chi tiết mà không tiêu quota.
- HTTP 429 được trình bày là lỗi quota của Agent, không phải firewall block; request kết thúc trong thời gian giới hạn.
- L0/L5 và các lớp bị bỏ qua được ghi đúng theo dữ liệu thực có.
- Layout dùng được trên desktop và mobile; kiểm tra build cùng các test mục tiêu.
- Gói online không chứa `.env`, token, key, dữ liệu phiên hay thông tin nhận dạng người dùng.

## Giới hạn phát hành

Frontend hiện gọi API FastAPI tại máy local. Bản web riêng tư có thể phát lại các trace đã lưu, nhưng không thể gọi Agent trực tiếp cho người xem cho đến khi có backend HTTPS được triển khai và cấu hình. LLM Judge và Power Agent giữ key riêng; không đưa secret vào JavaScript phía trình duyệt.
