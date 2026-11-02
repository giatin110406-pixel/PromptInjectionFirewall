# H2/H3 — bản sửa theo nghiên cứu nguồn công khai

Nguồn nội dung vẫn là **AI tổng hợp**. Trường `author` được bỏ theo yêu cầu trước; `authorship: ai_generated` và `assigned_to` được giữ. Nguồn web dùng để tham khảo thiết kế tình huống và hình thức chứng từ, không phải lấy nguyên văn hoặc dịch mẫu vào dữ liệu. Bộ này chưa thay thế yêu cầu dữ liệu do người viết.

## File và tính tương thích

| Bộ | File | Số dòng | Phạm vi |
|---|---|---:|---|
| H2 đầy đủ | `attack_scenarios_vi.jsonl` | **60** | 48 ca thuộc 7 hành động ban đầu + 12 ca egress WP3 |
| H3 | `friction_flows.jsonl` | **96** | 48 Việt, 48 Anh; tác vụ nghiệp vụ hợp lệ |
| H2 khóa enum cũ | `compatibility/core7/attack_scenarios_vi.jsonl` | **48** | Chỉ 7 hành động gốc |
| H3 cho cùng thư mục nạp | `compatibility/core7/friction_flows.jsonl` | **96** | Cùng H3 đầy đủ, gồm egress đã được dự án hỗ trợ |

H2 đầy đủ vẫn trong giới hạn **40–60 dòng**, có **16 ca không chỉ thị (26,7%)** và **12 tool JSON**. H2 core7 có **12/48 ca không chỉ thị (25%)**, **12 tool JSON**, đủ refund, transfer_money, data_access, role_escalation, password_reset, account_recovery, voucher_apply. Bản core7 là tập con, không cộng chung vào mẫu số với bộ đầy đủ.

Tên trường và kiểu dữ liệu gốc được giữ:

- H2: `id`, `domain`, `channel`, `content`, `target_action`, `attacker_value`, `notes` là chuỗi; `has_explicit_instruction` là boolean; `target_payload` là object. `attacker_value` có nguyên văn trong content và payload, kể cả trong mảng cc/share_with.
- H3: `user_messages` là mảng chuỗi không rỗng; `content` là `{source, text}`; `action` là `{type, payload}`. Enum domain/lang/destination_from/split giữ nguyên.
- Metadata bổ sung gồm assigned_to, authorship, review_status, revision, source_refs, document_format, family/situation; không thay các trường nghiệp vụ.

Bốn hành động WP3 bổ sung: send_email, share_file, http_request, post_message. Payload được kiểm tra bằng schema Pydantic hiện có tại `firewall/layer4.py`: địa chỉ gửi/chia sẻ là mảng, nội dung là chuỗi, URL có scheme, quyền file dùng view/comment/edit. Không thay schema adapter bằng schema API của Stripe hoặc Google Drive.

## Độ đa dạng và nghiệp vụ

| Chỉ số H3 | Trước | Sau |
|---|---:|---:|
| Số luồng | 96 | 96 |
| Lượt người dùng | 176 | 108 |
| Lượt khác nhau sau che số | 106 | **108/108** |
| Lần lặp khuôn cao nhất sau che số | 8 | **1** |
| Lần lặp sau che thêm email, URL, mã ID | — | **1** |

Số lượt giảm vì các câu nhập người nhận máy móc đã được gộp thành yêu cầu có ngữ cảnh ở nơi chỉ cần một lượt. Vẫn có tình huống nhiều lượt để bổ sung thông tin hoặc giới hạn phạm vi. Chỉ số này không chứng minh có 108 ý định khác nhau: nhiều luồng cố ý cùng loại hành động nhưng khác tình huống và nguồn đích.

**48 ca tiếng Anh là tình huống riêng**, không sinh bằng dịch 48 ca tiếng Việt. Một chủ đề có hai ca Việt/hai ca Anh nhưng khác hoàn cảnh, vật phẩm hoặc chứng từ. Đây là cách soạn đặc tả, không phải tuyên bố có kiểm chứng tự động hoàn hảo về tương đương ngữ nghĩa.

Tài liệu gồm email có người gửi/tiêu đề/nội dung trao đổi, phiếu trả hàng, thông báo nhân sự, biên bản nghiệm thu, phiếu ghi có, trang nhà cung cấp, nhận xét và tool JSON. Đã bỏ mở đầu chung “Chứng từ nghiệp vụ giả lập” và cách biến mọi tài liệu thành bảng khóa–giá trị. JSON vẫn giữ ở các ca thật sự là kết quả tool.

H2 trộn lệnh trực tiếp, HTML/CSS/comment/template ẩn, không dấu/teencode, CV, review, ticket, giả xác nhận và tráo đích thuần dữ liệu. Egress có thêm CC, chia sẻ ngoài phạm vi, POST credential giả và đăng liên hệ giả sang kênh ngoài.

## Phân bổ

H3: **48 user / 16 saved / 32 content**; saved dùng fixture `0451000123456` của demo_customer. Có **24 chủ đề**, mỗi chủ đề nằm trọn trong một split và có cả hai ngôn ngữ; tổng **48 dev / 48 test**.

Các nhóm saved tách giáo dục, hoàn ứng sức khỏe, sửa chữa nhà và tiền dịch vụ định kỳ. Hồ sơ cá nhân tách lao động, tiền lương/thời gian, đào tạo và bàn giao tài sản. Chia theo chủ đề không có nghĩa toàn bộ một loại hành động phải nằm trong một split.

| Phụ trách | H2 đầy đủ | H2 core7 | H2 egress | H3 | H3 egress |
|---|---:|---:|---:|---:|---:|
| Tín | 15 | 12 | 3 | 24 | 8 |
| Thịnh | 15 | 12 | 3 | 24 | 8 |
| Khang | 15 | 12 | 3 | 24 | 8 |
| Thắng | 15 | 12 | 3 | 24 | 8 |

Phần riêng ở `by_assignee/tin`, `thinh`, `khang`, `thang`; assignment.csv hỗ trợ Excel. Mỗi người có H3 12 Việt/12 Anh, 12 dev/12 test, nguồn 12 user/4 saved/8 content.

Egress H2: **12 ca** (4 email, 4 share_file, 2 HTTP, 2 post_message). H3: **32 luồng** (12 email, 12 share_file, 4 HTTP, 4 post_message). Ca hợp lệ nêu mục đích và phạm vi gửi được phép; đích chỉ trong tài liệu vẫn là luồng hợp lệ để đo độ phiền, không đổi nhãn theo quyết định model.

## Nguồn nghiên cứu

Đã đọc [BANKING77](https://github.com/PolyAI-LDN/task-specific-datasets), [MultiWOZ](https://github.com/budzianowski/multiwoz), [CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/), [InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent), [AgentDojo](https://github.com/ethz-spylab/agentdojo), [Stripe Invoicing](https://docs.stripe.com/invoicing/integration) và [Google Drive sharing](https://developers.google.com/workspace/drive/api/guides/manage-sharing).

**SOURCES.json** ghi URL, giấy phép quan sát được, cách dùng và giới hạn. source_refs dẫn tới ID tài liệu tham khảo, không phải ID của mẫu công khai gốc. Không nhập mẫu benchmark vốn đã có trong tập đo dự án. Việc tham khảo nguồn công khai không khiến các dòng mới thành dữ liệu người viết.

Mọi danh tính, email, tài khoản, URL và nội dung nhạy cảm đều hư cấu; dùng example.com/evil.example. Hoàn tiền dùng USD theo schema hiện tại; chuyển khoản dùng VND. Một số khoản hoàn hợp lệ vượt ngưỡng duyệt tự động: không chọn tiền hay câu chữ để ép ALLOW. Các luồng đặt lại mật khẩu hợp lệ giả định bước xác minh đã thực sự hoàn tất trước hành động.

## Kiểm tra và tích hợp

```powershell
.\.venv\Scripts\python.exe evaluation/validate_h2_h3_review_drafts.py
.\.venv\Scripts\python.exe -m pytest tests/test_data_provenance.py -q
```

validation.json kiểm tra cấu trúc, payload, định lượng, nguồn đích, split, nguồn và độ trùng; revision_comparison.json lưu số liệu trước/sau. **Không gọi bộ phát hiện, không lấy điểm L2, không chạy action gate và không sửa câu theo quyết định firewall.** Nguồn đích kiểm tra theo sự xuất hiện literal và fixture, không ép khớp khả năng trích nguồn tin cậy của engine.

Phần ghi nguồn trong evaluation/eval_v4.py nhận biết authorship: ai_generated khi không có author. assigned_to không được suy thành tác giả; dữ liệu thiếu khai báo nguồn không bị mặc định coi là người viết. Kiểm tra loader và schema chưa phải đo ASR/friction.

Hai thư mục đầy đủ và compatibility/core7 đều dùng được với --data-dir và giữ tên file chuẩn. Bộ core7 chỉ giới hạn enum H2; H3 vẫn có egress nên cần engine đã hỗ trợ WP3.

Tái tạo bằng `python data/scripts/build_h2_h3_review_drafts.py`. Từng ca được viết trong `data/scripts/h2_h3_curated_v2.py`; builder chỉ chèn ID/địa chỉ và đóng gói. Builder ghi đè bản nháp, cần lưu riêng trước khi sửa tay. Bản cũ nằm ở `artifacts/h2_h3_ai_draft_4_assignees_before_research.zip`.