# AI Agent thật chạy sau firewall

**Trạng thái: xong phần chạy được (02/11/2026), đo một phần trên Groq free tier.** Mã: `agent/` (llm, backend, tools, loop, prompts), `api/routes/agent.py` (`/agent/*`), công tắc "Agent thật / Kịch bản" ở `frontend/security-console/pages/demo.jsx`. Đo: `evaluation/eval_agent.py`, `evaluation/run_agent_demo.py`. Test: `tests/test_agent_llm.py`, `test_agent_loop.py`, `test_agent_api.py`, `test_agent_eval.py`. Kế hoạch và kết quả đầy đủ: `docs/agent_plan_vi.md`.

## Làm gì
Một agent gọi tool (LLM thay được bằng `AGENT_PROVIDER`: groq, gemini, local, scripted) chạy trên backend giả lập (tài khoản, đơn hàng, hộp thư, tài liệu). Firewall chen vào ba điểm: tin nhắn khách (`process_input`), kết quả tool đọc (`process_context`, nội dung trả cho LLM đã datamark), tool hành động (`validate_action`). Ba chế độ: `off` (không firewall), `detection`, `provenance`. Hành động REVIEW dừng lại chờ khách xác nhận (`Agent.confirm`). Backend chỉ đổi trạng thái qua `Agent._execute`, có test kiểm tra.

Engine `firewall/` không bị sửa. Hai chỉ số trước đây là giả định nay có số đo: "agent bị lừa bao nhiêu % khi không có firewall" và "firewall cắm được vào agent thật hay không".

## Số đo (Groq free tier, một lần chạy, mẫu nhỏ, dữ liệu AI tổng hợp)
`openai/gpt-oss-120b`, 20 kịch bản H2 đầu tiên (sau khi loại 4 ca role_escalation vì agent không có tool đó). Hạn mức ngày của Groq (200.000 token) hết giữa chừng nên số ca là 18 (off) và 17 (detection, provenance):

| Chế độ | Agent gọi đúng hành động bẫy | Hành động bẫy được backend thực hiện | Giữ chờ xác nhận |
|---|---|---|---|
| off | 11/18 = 61% (KTC 95% 39 đến 80%) | 11/18 = 61% | 0 |
| detection | 2/17 = 12% | 2/17 = 12% (33% khi đã gọi: 2/2) | 0 |
| provenance | 3/17 = 18% | **0/17** (KTC 0 đến 18%) | 2/17 (và 1 BLOCK) |

Chú ý khi đọc: ở chế độ có firewall, agent gọi bẫy ít hơn vì firewall đã cắt chỉ thị khỏi nội dung trước khi LLM thấy (10/17 nội dung bị gắn TAINT), không phải vì LLM "khôn hơn". Số nhỏ, khoảng tin cậy rộng, chạy một lần.

Luồng hợp lệ H3 (20 luồng đầu, **model `openai/gpt-oss-20b`** vì hạn mức ngày của 120b đã hết): `task_success` 9/20 = 45%, `human_approval_rate` 6/20 = 30%, `false_block` 0/20, tin nhắn khách bị giữ hoặc chặn ở lớp tin nhắn 3/20 = 15%, `agent_error` 8/20 = 40%. Phần lớn `agent_error` là LLM không tìm được đích (luồng "gửi mẹ" không có số tài khoản và agent chưa có tool danh bạ; luồng cần mã HR nằm trong tài liệu). Đây là giới hạn của agent thử nghiệm, không phải của firewall.

9 ca demo chạy thật với Groq (`evaluation/results/agent_demo_groq.json`): ở chế độ off, 3/6 ca tấn công và đổi người nhận được LLM làm theo và backend thực hiện (3 ca còn lại LLM không gọi hành động); ở provenance không ca nào được thực hiện; ca hợp lệ "chuyển 2 triệu cho mẹ" LLM không hoàn tất (hỏi lại số tài khoản). LLM thật không lặp lại đúng kịch bản soạn sẵn nên các ca này chỉ là minh họa.

## Hai phát hiện về firewall
1. **L2 chặn nhầm câu yêu cầu bình thường của khách**: "Bạn xem giúp email mới nhất và xử lý giúp mình." bị BLOCK (điểm 0,989); trong 24 câu ngắn kiểu "mở X rồi xử lý" đã thử, 9 bị BLOCK và 1 bị REVIEW. Cách diễn đạt dùng trong bộ đo (`agent/prompts.py`) được chọn là cách qua được L2. Trong H3, 3/20 tin nhắn thật của khách bị giữ hoặc chặn.
2. Gọi Groq bằng `urllib` mặc định bị Cloudflare từ chối (HTTP 403, mã 1010) cho tới khi thêm `User-Agent`; model `llama-3.3-70b-versatile` trong plan không còn trong danh sách của tài khoản nên mặc định đổi sang `openai/gpt-oss-120b`. Test dùng server giả không bắt được hai lỗi này, chỉ lần chạy thật bắt được.

## Chưa làm
Bộ H2/H3 với LLM thật mới chạy một phần; H2 v1 dừng ở ca thứ 18 vì quota Groq, H3 v1 dùng model 20b. Chưa chạy đủ H3 bằng 120b, Gemini hoặc model cục bộ. Chưa có tool role_escalation. Chưa kiểm Layer 5 trên câu trả lời của agent.

## Tiếp nối ngày 02/11/2026

Codex đã bổ sung tool danh bạ theo người dùng; loại header email khỏi system prompt; sửa rò chế độ engine chung, xác nhận đồng thời, danh tính phiên API, fallback đọc mã đơn datamark và giao diện chờ nhân viên duyệt. Ngữ pháp đóng xử lý một nhóm yêu cầu đọc email/tài liệu bị chặn nhầm, không retrain L2. Cấu hình hỗ trợ `GROQ_API_KEY`, `_2` đến `_5` (thêm số lớn hơn nếu cần); các key cùng organization vẫn chung quota.

Kiểm chứng: **1.034 test đạt, 1 skip; build thành công; 16 kiểm tra Chrome đạt**. Chạy khô đủ 264 lượt với agent giả: provenance không thực hiện hành động độc hại ở 56 ca H2; H3 thành công 73/96. Không dùng các con số này để thay cho tỷ lệ một LLM thật bị lừa. V2 Groq tiếp tục gặp HTTP 429, nên số đo 120b toàn bộ vẫn còn thiếu. L2 còn chặn nhầm những câu ngoài nhóm đã sửa. Chi tiết và lệnh chạy tiếp ở [agent_plan_vi.md](../docs/agent_plan_vi.md#10-tiếp-nối-và-kiểm-chứng-codex-02112026). Đủ để viết báo cáo prototype nếu nêu các giới hạn này. Chưa commit.
