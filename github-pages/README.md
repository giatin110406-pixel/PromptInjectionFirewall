# AI Firewall — GitHub Pages

## Trang nhóm trên GitHub Pages

- Trang giới thiệu nhóm và dự án: https://giatin110406-pixel.github.io/PromptInjectionFirewall/
- Workflow: `.github/workflows/pages.yml` tự xuất bản thư mục `github-pages` khi source trang thay đổi trên nhánh `main`, hoặc chạy bằng `workflow_dispatch`.
- Demo Agent chạy local theo hướng dẫn trong README của repo; không triển khai demo lên internet.

Ngày 04/11/2026, chuyển trang giới thiệu từ ChatGPT Sites sang GitHub Pages theo yêu cầu. Hai bản Sites cũ đã được tắt quyền truy cập công khai. Thư mục này giữ source HTML/CSS và dữ liệu tổng hợp của trang giới thiệu; API, model, key và dữ liệu phiên của demo không nằm trong artifact triển khai.

Website tĩnh giới thiệu dự án, không cần cài đặt hay build. Mở `index.html` để xem trên máy.

## Xuất bản bằng GitHub Pages

1. Source nằm trong thư mục `github-pages`. Repo dùng **Settings → Pages → Build and deployment → GitHub Actions**.
2. Push thay đổi source trang lên `main`, hoặc mở **Actions → Publish project hub to GitHub Pages → Run workflow**. Workflow chỉ tải thư mục `github-pages` lên Pages.
3. Kiểm tra quyền đọc repository và từng tài liệu. Nếu repository riêng tư, người chấm cần được cấp quyền; các link tài liệu có thể không mở được với người ngoài.
4. Cập nhật URL trang nhóm và URL repository vào README sản phẩm nộp.

## Cần nhóm bổ sung

- Danh sách thành viên, vai trò, thông tin liên hệ nội bộ phù hợp và thỏa thuận thành lập nhóm.
- Link backlog, biên bản họp, RACI, demo/video và các bản tài liệu mới nhất đã được xác nhận.
- Kiểm tra nhánh `main` đã chứa các tài liệu được liên kết; link hiện trỏ đến repository `giatin110406-pixel/PromptInjectionFirewall`.
- Đối chiếu các số liệu với bản báo cáo cuối cùng trước khi xuất bản và cập nhật thường xuyên.

Không đưa thông tin cá nhân hoặc tài liệu nội bộ lên trang công khai khi chưa được nhóm đồng ý.
