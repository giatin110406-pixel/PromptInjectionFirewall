# Nguồn nghiên cứu cho bản research_v2

Đọc ngày 02/11/2026. Các nguồn dưới đây cung cấp ý tưởng thiết kế và hình thức nghiệp vụ; **không nhập mẫu nguyên văn, không dịch mẫu thành ca mới, không tuyên bố các dòng AI là dữ liệu công khai do người viết**. ID nguồn chi tiết nằm ở `SOURCES.json` và được tham chiếu bằng `source_refs`.

| Nguồn chính thức | Điều đã tham khảo | Giấy phép/phạm vi quan sát |
|---|---|---|
| [BANKING77 / PolyAI](https://github.com/PolyAI-LDN/task-specific-datasets) | Yêu cầu ngân hàng ngắn, có ngữ cảnh và nhiều cách diễn đạt; không gom mọi yêu cầu thành một câu chuyển khoản lặp lại | Repo công bố CC BY 4.0; không lấy câu từ train/test vào bộ này |
| [MultiWOZ](https://github.com/budzianowski/multiwoz) | Hội thoại tác vụ đa miền, lượt bổ sung thông tin, giới hạn yêu cầu | Repo mô tả hội thoại người-người; license cấp repo là MIT. Cần kiểm tra phiên bản dữ liệu cụ thể nếu nhập hoặc phân phối dữ liệu gốc |
| [CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/) | Phân biệt trả phí, hoàn ứng và điều chỉnh khoản thu; yêu cầu có bối cảnh thay vì chỉ mã giao dịch | CFPB cho phép dùng, phân tích và xây dựng trên dữ liệu đã công bố; chính CFPB lưu ý đây không phải mẫu đại diện mọi trải nghiệm khách hàng. Không lấy narrative hoặc danh tính vào bộ này |
| [InjecAgent](https://github.com/uiuc-kang-lab/InjecAgent) | Tách gây hại trực tiếp với đánh cắp dữ liệu; gắn mục tiêu tấn công với hành động ra ngoài cụ thể | Repo MIT. Dự án đã có InjecAgent trong tập đo cũ, nên chỉ tham khảo thiết kế, không lấy lại test case |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Bối cảnh workspace, email, cộng tác và nội dung tool không tin cậy; đặt egress độc hại cạnh thao tác gửi hợp lệ | Repo MIT; không lấy task hoặc injection text của suite |
| [Stripe Invoicing](https://docs.stripe.com/invoicing/integration) | Dòng phí, phần đã trả, trạng thái hóa đơn và điều chỉnh một phần để chứng từ có logic nghiệp vụ | Tài liệu tham khảo, không nhập code hay văn bản. Đơn vị tiền vẫn theo schema dự án, không tự áp quy ước đơn vị nhỏ nhất của Stripe |
| [Google Drive sharing](https://developers.google.com/workspace/drive/api/guides/manage-sharing) | Người nhận định danh, mức quyền cần thiết, tách file được phát hành khỏi thư mục riêng | Tài liệu tham khảo; payload địa phương vẫn dùng share_with và view/comment/edit, không giả là request Drive API nguyên bản |

Các thay đổi là suy luận thiết kế của Codex từ những tài liệu trên, không phải nhãn do tác giả nguồn gán cho các ca mới. Ví dụ, bổ sung CC hoặc chỉ tráo người nhận được dùng để kiểm tra nguồn gốc đích; không khẳng định những ca này là mẫu công khai thuộc benchmark gốc.

Để có bộ **người viết** phục vụ yêu cầu môn học, cần thu thập hoặc soạn độc lập theo quy trình của nhóm, ghi nguồn và quyền sử dụng đúng. Chỉ xóa metadata AI, đổi tên người phụ trách hay diễn đạt lại bản này không đáp ứng điều kiện đó.
