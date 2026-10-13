# AI System Card: AI Firewall cho AI Agent (v2)

Chi tiết kiến trúc: xem `docs/engine_architecture_vi.md`.

## 1. Tổng quan
- **Tên**: AI Firewall for AI Agents
- **Phiên bản**: 2.0 (thiết kế chốt, đang triển khai)
- **Chức năng**: lọc input người dùng và nội dung không tin cậy, kiểm soát tool call, lọc output. Quyết định: ALLOW / SANITIZE / REVIEW / BLOCK.

## 2. Thành phần
L0 Normalize, L1 Signatures, L2 Classifier đa ngữ, L3 LLM judge, Spotlighting, L4 Action Firewall, L5 Output Guard, Session Risk.

## 3. Mô hình và dữ liệu
- L2: fine-tune `mdeberta-v3-base` (hoặc Prompt Guard 2) trên dữ liệu EN+VI.
- L3: LLM qua prompt có phiên bản.
- L4 anomaly: Isolation Forest trên log tool call.
- Session Risk: model nhỏ trên chuỗi điểm rủi ro.
- Dữ liệu: BIPIA, dữ liệu prompt injection công khai, dữ liệu tiếng Việt (dịch, sinh, tự viết). Dữ liệu dịch/sinh bằng AI được khai báo trong AI Use Disclosure Log.

## 4. Hiệu năng
**Chưa có số đo hợp lệ cho v2.** Số liệu của bản cũ (recall ~99%, ROC-AUC 0.9998) đã bị thu hồi vì: tập dữ liệu gốc không còn, eval chưa chạy qua Layer 2/3, và dữ liệu L3 cũ bị leakage nguồn (toàn bộ mẫu độc hại từ BIPIA, toàn bộ mẫu an toàn từ GPT-4o-mini). Số liệu sẽ được cập nhật sau khi chạy eval trên tập test sạch.

## 5. Mục đích và giới hạn
- **Dùng cho**: chatbot chăm sóc khách hàng, copilot nội bộ, agent có tool.
- **Không dùng cho**: ảnh/âm thanh, thay thế hoàn toàn kiểm soát truy cập của hệ thống backend, quyết định nhạy cảm không có người duyệt.
- **Rủi ro**: false positive chặn nhầm khách hàng, câu tiếng Việt không dấu/teencode, tấn công thích ứng, model drift.
- **Kiểm soát**: human-in-the-loop qua REVIEW, fail-closed khi model lỗi, incident log, monitoring.
- **Owner sau go-live**: Tech Lead (vận hành), AI Lead (retrain).
