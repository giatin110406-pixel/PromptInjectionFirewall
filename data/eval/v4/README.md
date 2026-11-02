# Handoff v4 — bộ thử tổng hợp

`attack_scenarios_vi.jsonl` và `friction_flows.jsonl` do **OpenAI Codex tạo**, chưa có người kiểm tra độc lập. Trường `author` ghi nguồn ở từng dòng. Đây là bản thử để tích hợp công cụ đo, **chưa đáp ứng yêu cầu H2 “do người viết” và H3 “nhóm tự viết”** trong handoff.

Không mô tả số liệu từ hai file này là kết quả trên dữ liệu người viết. Nhóm cần tự viết bộ chính thức độc lập; việc chỉ đọc duyệt hoặc đổi tên tác giả không làm dữ liệu AI thành dữ liệu người viết. Giữ nguồn gốc của bản tổng hợp khi lưu trữ hoặc chỉnh sửa.

| File | Số dòng | Phân bố |
|---|---:|---|
| `attack_scenarios_vi.jsonl` | 48 | 32 chỉ thị, 16 chỉ có giá trị; 12 phản hồi tool JSON; đủ 7 loại hành động |
| `friction_flows.jsonl` | 96 | 48 VI / 48 EN; 48 dev / 48 test; đủ nguồn user / saved / content |

H2 mô tả **hành động agent bị dụ thực hiện**, không phải kết quả agent tự sinh qua LLM. Payload đã có các trường bắt buộc và được kiểm tra với luật cứng hiện tại để tránh ASR thấp giả vì payload thiếu trường. `identity_confirmed=true` trong ca tấn công là trạng thái agent bị dụ khai báo, không phải xác minh đã diễn ra thật.

H3 là tác vụ hợp lệ theo nghiệp vụ; chúng vẫn có thể bị model chặn nhầm hoặc cần REVIEW vì nguồn gốc. Không sửa nhãn “hợp lệ” theo quyết định model. `destination_from=saved` dùng người nhận giả lập đã có trong `firewall/trusted_book.yaml` cho `demo_customer`. Luồng xác minh tài khoản giả định bước xác minh nghiệp vụ đã hoàn tất; không có xác minh danh tính thật trong dữ liệu mẫu.

`family` của H3 gom cùng chủ đề và cả hai ngôn ngữ vào duy nhất một split. ID và giá trị đích là giả. Không thực thi hành động tài chính thật.

Kiểm tra bằng `python evaluation/validate_handoff_content.py`. Công cụ này báo kiểm tra cấu trúc và yêu cầu tác giả con người thành hai mục riêng. Xem bản bàn giao đầy đủ: `docs/handoff_noi_dung_ket_qua_vi.md`.
