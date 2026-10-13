# Risk Register: AI Firewall (v2)

| ID | Loại | Rủi ro | Khả năng | Tác động | Giảm thiểu | Owner | Trạng thái |
|---|---|---|---|---|---|---|---|
| R-01 | Data | **Leakage nguồn**: mẫu độc hại và an toàn đến từ hai nguồn khác nhau nên model học văn phong nguồn thay vì học injection | Cao (đã xảy ra với dữ liệu L3 cũ) | Cao | Sinh/dịch cả hai nhãn bằng cùng pipeline, chia train/test theo ID câu gốc trước khi dịch, kiểm tra bằng classifier chỉ dựa trên văn phong/nguồn | Data Lead | Đang xử lý |
| R-02 | Data | Thiếu dữ liệu tiếng Việt, hiệu năng VI thấp hơn EN | Cao | Cao | Dịch + sinh + tự viết, tập test VI người kiểm tra 100%, báo cáo metric tách ngôn ngữ | Data Lead | Mở |
| R-03 | Evaluation | Số liệu sai lệch: tập dữ liệu gốc mất, eval chưa chạy qua L2/L3, số liệu cũ trong tài liệu không tái lập được | Đã xảy ra | Cao | Thu hồi số cũ, chạy lại eval toàn pipeline, lưu dataset hash cùng kết quả | AI Lead | Đang xử lý |
| R-04 | Accuracy | False positive chặn nhầm khách hàng (câu không dấu, teencode, trộn Anh-Việt) | Trung bình | Cao | Thêm mẫu an toàn tiếng Việt đa dạng, dùng SANITIZE/REVIEW thay vì chặn cứng, theo dõi FPR | AI Lead | Mở |
| R-05 | Robustness | Lách bằng zero-width, homoglyph, base64, leetspeak, đổi ngôn ngữ | Cao | Trung bình | L0 Normalize, embedding đa ngữ, L2 đa ngữ | Tech Lead | Mở |
| R-06 | Security | Indirect injection qua tài liệu RAG, email, tool output | Cao | Cao | Quét chunk bằng L2, spotlighting, taint tracking ở L4 | Tech Lead | Mở |
| R-07 | Business Logic | Injection ép agent gọi tool trái phép (hoàn tiền lớn, lấy dữ liệu nhạy cảm) | Cao | Nghiêm trọng | L4 policy-as-code, taint tracking, hạn mức, REVIEW cho hành động nhạy cảm | Tech Lead | Mở |
| R-08 | Operations | Model không load được và hệ thống âm thầm quay về heuristic | Trung bình | Cao | Fail-closed hoặc trạng thái `degraded` ở health check và trace | Tech Lead | Mở |
| R-09 | Latency/Cost | LLM judge vượt ngân sách trễ và chi phí | Trung bình | Trung bình | Chỉ gọi L3 cho <5% traffic, cost cap, cache | PM | Mở |
| R-10 | Drift | Tấn công mới làm giảm hiệu năng theo thời gian | Cao | Trung bình | Feedback loop từ REVIEW, retrain định kỳ, monitoring | AI Lead | Mở |
| R-11 | Privacy | Log chứa PII của người dùng | Trung bình | Cao | L5 lọc PII, che dữ liệu trong incident log, giới hạn truy cập | Governance Lead | Mở |
