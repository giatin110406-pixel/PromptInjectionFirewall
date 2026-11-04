# AI Firewall — GitHub Pages

## Các trang đang công khai

- Trang giới thiệu nhóm và dự án: https://ai-firewall-project-hub.aridlapis.chatgpt.site
- Demo trực quan: https://firewall-request-trace.aridlapis.chatgpt.site

Đã xuất bản qua Sites ngày 04/11/2026, cho phép mọi người có link truy cập. Demo online phát lại trace đã lưu; Agent gọi LLM trực tiếp vẫn cần backend HTTPS riêng. Thư mục này giữ source HTML/CSS và dữ liệu tổng hợp của trang giới thiệu; tên `github-pages` không có nghĩa GitHub Pages đã được bật.

Website tĩnh giới thiệu dự án, không cần cài đặt hay build. Mở `index.html` để xem trên máy.

## Xuất bản bằng GitHub Pages

1. Đưa thư mục `github-pages` lên repository. Trong GitHub, vào **Settings → Pages → Build and deployment** và chọn **GitHub Actions**.
2. Tạo workflow triển khai với thư mục artifact `github-pages`, hoặc đưa nội dung thư mục này vào một repository riêng rồi chọn triển khai từ branch và thư mục root. URL chính xác phụ thuộc repository và cấu hình GitHub Pages.
3. Kiểm tra quyền đọc repository và từng tài liệu. Nếu repository riêng tư, người chấm cần được cấp quyền; các link tài liệu có thể không mở được với người ngoài.
4. Cập nhật URL trang nhóm và URL repository vào README sản phẩm nộp.

## Cần nhóm bổ sung

- Danh sách thành viên, vai trò, thông tin liên hệ nội bộ phù hợp và thỏa thuận thành lập nhóm.
- Link backlog, biên bản họp, RACI, demo/video và các bản tài liệu mới nhất đã được xác nhận.
- Kiểm tra nhánh `main` đã chứa các tài liệu được liên kết; link hiện trỏ đến repository `giatin110406-pixel/PromptInjectionFirewall`.
- Đối chiếu các số liệu với bản báo cáo cuối cùng trước khi xuất bản và cập nhật thường xuyên.

Không đưa thông tin cá nhân hoặc tài liệu nội bộ lên trang công khai khi chưa được nhóm đồng ý.
