# Project Charter: AI Firewall cho AI Agent

## 1. Vấn đề
AI agent trong chăm sóc khách hàng, tài chính và vận hành nội bộ bị đe dọa bởi prompt injection (trực tiếp và gián tiếp qua tài liệu/email/tool output), leo thang đặc quyền và lạm dụng tool. Model nền đã chặn jailbreak trong chat khá tốt, nhưng không kiểm soát được hành động của agent, không xử lý tốt nội dung không tin cậy, và yếu với tiếng Việt. Regex thuần có recall thấp (~37% trong baseline cũ), còn hỏi LLM cho mọi input thì chậm và tốn kém.

## 2. Mục tiêu và tiêu chí thành công
Các ngưỡng dưới đây là **mục tiêu**, chưa phải kết quả.
- Recall > 90% trên tập test tiếng Anh và > 85% trên tập test tiếng Việt, đo riêng từng ngôn ngữ.
- False positive rate < 3% trên câu hỏi chăm sóc khách hàng thật (EN và VI).
- p95 latency cho đường nhanh (L0-L2) < 50ms trên CPU.
- 100% hành động vượt hạn mức hoặc sai quyền bị L4 chặn hoặc chuyển REVIEW.
- Có trace giải thích được cho từng quyết định.

## 3. Phạm vi
- **Trong phạm vi**: L0 Normalize, L1 Signatures, L2 Classifier đa ngữ, L3 LLM judge, Spotlighting, L4 Action Firewall, L5 Output Guard, Session Risk, FastAPI, SOC console, đánh giá EN/VI.
- **Ngoài phạm vi**: ảnh/âm thanh, hạ tầng huấn luyện phân tán, thay thế kiểm soát truy cập backend.

## 4. Phương án AI (Build vs Buy)
Hybrid: **buy** model nền mở (mDeBERTa/Prompt Guard 2, LLM judge), **build** phần fine-tune tiếng Việt, Action Firewall và anomaly detector. Rule làm baseline và hàng rào tất định. Chi tiết: `docs/engine_architecture_vi.md`.

## 5. Mốc thời gian (4 sprint)
- **Sprint 1 (Tuần 2-3)**: Business Understanding, Charter, KPI tree, Risk Register v1.
- **Sprint 2 (Tuần 4-5)**: Data Audit (sửa leakage), dữ liệu EN+VI, Data Dictionary, EDA, baseline, Metrics v1, Model Selection Matrix.
- **Sprint 3 (Tuần 6-7)**: L0-L2 bản v2, L4 YAML/taint/REVIEW, evaluation EN/VI, deployment plan v1.
- **Sprint 4 (Tuần 8-9)**: L3, L5, Session Risk, demo, AI System Card, final report, slides.
