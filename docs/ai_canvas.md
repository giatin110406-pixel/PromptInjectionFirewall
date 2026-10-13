# AI Project Canvas: AI Firewall cho AI Agent (v2)

Chi tiết kiến trúc: xem `docs/engine_architecture_vi.md` (nguồn sự thật duy nhất).

## 1. Value Proposition
Runtime security cho AI agent: phát hiện prompt injection (kể cả indirect injection trong tài liệu RAG, email, tool output) và kiểm soát hành động của agent theo quyền và chính sách, hỗ trợ tiếng Anh và tiếng Việt.

## 2. Người dùng và bài toán
- Đội phát triển/vận hành chatbot và agent có quyền dùng tool (hoàn tiền, truy cập dữ liệu).
- Pain point: model nền chặn jailbreak khá tốt nhưng không kiểm soát được hành động của agent và nội dung không tin cậy.

## 3. Data Strategy
- **Nguồn**: BIPIA (indirect injection), tập prompt injection công khai, dữ liệu tiếng Việt do nhóm dịch/sinh/tự viết.
- **Ground truth**: nhãn nhị phân (benign/malicious) kèm `attack_type`. Mẫu an toàn và độc hại phải **cùng nguồn và cùng pipeline sinh** để tránh leakage nguồn.
- **Tập test tiếng Việt**: 300-500 mẫu, người kiểm tra 100%, không dùng để train.
- Trạng thái dữ liệu: xem `docs/data_audit_report.md`.

## 4. Kiến trúc AI (tóm tắt)
| Layer | AI |
|---|---|
| L0 Normalize | 0% |
| L1 Signatures (regex EN/VI + embedding đa ngữ) | ~40% |
| L2 Classifier đa ngữ (mDeBERTa fine-tune) | 100% |
| L3 LLM judge (ca lưng chừng) | 100% (prompt, không train) |
| Spotlighting | 0% |
| L4 Action Firewall (policy + anomaly detector) | ~35% |
| L5 Output Guard (canary, PII) | ~25% |
| Session Risk | 100% |

Rule làm baseline và hàng rào tất định. AI làm phần phát hiện ngữ nghĩa mà rule không bắt được.

## 5. Baseline và đánh giá
- **Baseline**: regex-only. Số liệu cũ (Recall 36.93%, Precision 100%, F1 53.94% trên 738 mẫu) nằm ở `evaluation/results/baseline_metrics.json`; tập 738 mẫu không còn trên đĩa nên cần chạy lại trên tập mới.
- **So sánh**: XGBoost feature (bản cũ), Prompt Guard / Llama Guard (nguồn mở), L2 mDeBERTa đã fine-tune.
- **Metric**: precision, recall, F1, FPR, p95 latency, tách riêng EN / VI / trộn lẫn. Chưa có số đo hợp lệ cho v2.

## 6. Triển khai
FastAPI + Next.js demo (chat bên trái, SOC console bên phải). Mục tiêu: đóng gói thành proxy đặt trước API LLM.
