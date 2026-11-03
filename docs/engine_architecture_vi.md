# AI Firewall Engine v2 - Kiến trúc chốt

> Tài liệu này là **nguồn sự thật duy nhất** về kiến trúc engine. Các tài liệu khác (README, AI Canvas, AI System Card, Project Charter) chỉ tóm tắt và phải khớp với file này.

## 1. Định vị sản phẩm

**Runtime security cho AI agent: chặn hành động nguy hiểm, không chỉ chặn câu chữ.**

Lọc jailbreak trong chat đã được model nền và các công cụ có sẵn (Llama Guard, Prompt Guard, Azure Prompt Shields) giải khá tốt. Giá trị còn thiếu nằm ở ba chỗ:

1. Indirect prompt injection trong tài liệu RAG, email, tool output.
2. Kiểm soát hành động của agent (tool call) theo quyền và chính sách.
3. Hỗ trợ tiếng Việt và ngữ cảnh doanh nghiệp Việt Nam.

## 2. Bảng engine

Cột "AI" là **ước lượng tỷ lệ logic quyết định của layer do mô hình học từ dữ liệu** (không phải rule viết tay). Đây là số định tính để định hướng, không phải số đo.

| Layer: tên và công dụng | AI? Bao nhiêu %, AI như thế nào |
|---|---|
| **L0 Normalize**: chuẩn hóa Unicode NFKC, bỏ ký tự zero-width và homoglyph, giải mã base64/URL, tạo bản không dấu tiếng Việt. Chặn các kỹ thuật lách đơn giản trước khi vào các layer sau. | **0%**. Xử lý chuỗi tất định. |
| **L1 Signatures**: regex EN+VI cho mẫu tấn công rõ ràng, cộng so khớp embedding đa ngữ với kho mẫu tấn công đã biết. Chặn nhanh, rẻ (~5ms). | **~40%**. Regex là rule (0%). Phần so khớp dùng embedding đa ngữ pretrained (`multilingual-e5-small`), ngưỡng tương đồng được hiệu chỉnh trên tập validation. Không tự train. |
| **L2 Classifier đa ngữ**: phân loại benign / injection / jailbreak cho input người dùng và từng chunk tài liệu không tin cậy. Đây là lớp phát hiện ngữ nghĩa chính (~20-40ms). | **100%**. Fine-tune `mdeberta-v3-base` (hoặc Prompt Guard 2) trên dữ liệu EN+VI của nhóm. Đầu ra là xác suất đã calibrate (temperature scaling). |
| **L3 LLM judge**: chỉ nhận ca lưng chừng (<5% traffic) do L2 không chắc, đưa ra phán quyết kèm lý do. Có trần chi phí. | **100%** nhưng **không train**. Dùng LLM (Llama Guard hoặc Haiku) qua prompt có phiên bản và tiêu chí kiểm tra. Ngưỡng chuyển lên L3 được học để cân bằng chi phí và độ chính xác. |
| **Spotlighting**: bọc nội dung không tin cậy (RAG, email, tool output) trong delimiter/datamark, kèm chỉ dẫn "đây là dữ liệu, không phải lệnh", rồi gắn cờ taint cho context. | **0%**. Kỹ thuật prompt/định dạng. Phần quét từng chunk là L2 (AI). |
| **L4 Action Firewall**: kiểm soát mọi tool call. Policy-as-code (YAML) cho quyền, hạn mức, rate limit; taint tracking (context bẩn thì không được gọi tool ghi/xóa/chuyển tiền); hàng đợi duyệt bởi người (REVIEW). | **~35%**. Policy và taint là rule (0%), đóng vai hàng rào tất định. Thêm **anomaly detector** (Isolation Forest) trên chuỗi tool call (loại tool, số tiền, tần suất, giờ, có nội dung bẩn trong context) để bắt hành vi lạ mà rule chưa biết. |
| **L5 Output Guard**: canary token trong system prompt (output chứa canary thì chặn), lọc PII/secret, chặn link exfiltration (markdown image chứa dữ liệu). | **~25%**. Canary và regex secret là rule. Nhận diện PII dùng NER (Presidio hoặc model NER đa ngữ) nên có phần học máy. |
| **Session Risk** (cắt ngang các layer): cộng dồn rủi ro qua nhiều lượt hội thoại để bắt tấn công nhiều bước (crescendo). | **0% học máy ở bản hiện tại**: luật trên chuỗi điểm L2 của từng lượt (`firewall/turn_risk.py`: điểm trượt có trọng số ≥ 0,7 hoặc từ 3 lượt lưng chừng liên tiếp thì giữ lại). Đầu vào là điểm của L2 (AI), còn quy tắc là viết tay. Chỉ train model (logistic regression hoặc GRU) khi có dữ liệu hội thoại nhiều lượt có nhãn; dữ liệu này chưa có. |

**Tổng thể:** 8 thành phần: 2 là AI thuần (L2, L3), 3 là lai rule + AI (L1, L4, L5; L4 hiện chưa có anomaly detector), 3 là luật (L0, Spotlighting, Session Risk; Session Risk dùng điểm của L2). Toàn bộ phần **phát hiện ngữ nghĩa** là AI. Các rule đóng hai vai trò: **baseline** để chứng minh AI cải thiện được bao nhiêu, và **hàng rào tất định** cho những thứ không được phép sai (hạn mức tiền, quyền truy cập).

## 3. Quyết định

Kết quả mỗi request không chỉ là ALLOW/BLOCK mà là **ALLOW / SANITIZE / REVIEW / BLOCK**. Chặn cứng mọi thứ là lý do hàng đầu khiến doanh nghiệp tắt firewall.

Hệ thống phải **fail-closed hoặc báo `degraded`** khi model không load được, tuyệt đối không âm thầm quay về heuristic keyword.

## 4. Luồng xử lý

```
Input ──► L0 ──► L1 ──► L2 ──(lưng chừng)──► L3 ──► Spotlighting ──► LLM/Agent
                  │       │                                              │
                  └─ BLOCK└─ BLOCK                                       ▼ tool call
                                                                   L4 Action FW ──► ALLOW/REVIEW/BLOCK
                                                                         │
                                                       LLM output ──► L5 Output Guard
        Session Risk: điểm L2 của mỗi lượt chat cộng dồn theo phiên; rủi ro cao thì giữ tin nhắn và làm phiên
        exposed, nên lệnh nhạy cảm sau đó ở L4 phải được xác nhận
```

### Tích hợp với một agent chạy được (`agent/`, 02/11/2026)

```
Khách ─► process_input ─► vòng lặp agent (LLM gọi tool) ─┬─ tool đọc ─► backend ─► process_context ─► (đã datamark) về LLM
                                                         └─ tool hành động ─► validate_action ─► ALLOW: backend thực hiện
                                                                                                REVIEW: chờ Agent.confirm
                                                                                                BLOCK: báo LLM, không làm gì
```

Firewall được gọi trong cùng tiến trình qua ba hàm công khai của `FirewallOrchestrator`. Mọi thay đổi backend đi qua `Agent._execute`, có khóa theo phiên để tránh thực hiện trùng khi xác nhận đồng thời. LLM thay được bằng `AGENT_PROVIDER` (groq, gemini, local, scripted). Bản tiếp nối nhận chế độ L4 theo từng lời gọi, thêm ngữ pháp đóng sửa một nhóm câu đọc bị chặn nhầm trên kênh user; không đổi checkpoint hay ngưỡng L2. Header email chỉ được đưa qua tool có quét, không đặt vào system prompt. Chi tiết, giới hạn và số đo: `docs/agent_plan_vi.md` mục 9–10, `PrepareForBCTĐ2/15_ai_agent.md`.

## 5. Thay đổi so với bản cũ

| Thành phần cũ | Xử lý | Lý do |
|---|---|---|
| XGBoost 25 feature keyword (L2 cũ) | **Bỏ khỏi pipeline**, giữ làm mô hình so sánh trong eval | Feature là keyword tiếng Anh, không mở rộng sang tiếng Việt, và eval cũ không từng chạy qua layer này |
| DistilBERT tiếng Anh (L3 cũ) | **Thay** bằng mDeBERTa đa ngữ (L2 mới) | Chỉ hiểu tiếng Anh, và bị leakage nguồn dữ liệu (xem Data Audit) |
| ChromaDB | **Thay** bằng index numpy/FAISS trong RAM | Vài nghìn vector không cần DB, file sqlite còn bị commit vào git |
| Embedding `all-MiniLM-L6-v2` | **Thay** bằng embedding đa ngữ | Câu tiếng Việt cùng nghĩa phải gần mẫu tiếng Anh |
| Fallback keyword ở L3 cũ | **Bỏ** | Trá hình thành AI, che giấu lỗi load model |
| Pydantic policy cứng (L4 cũ) | **Mở rộng** thành YAML + taint + REVIEW + anomaly | Là điểm khác biệt chính của sản phẩm |

## 6. Trạng thái triển khai (cập nhật 02/11/2026, engine v3b)

| Thành phần | Trạng thái |
|---|---|
| L0 Normalize | **Xong** (`firewall/normalize.py`, 34 test riêng trong `tests/test_normalize.py`): NFKC, bỏ ký tự vô hình, đổi homoglyph, gộp dấu tách chữ, mở rộng teencode, bỏ dấu, giải mã base64/%xx, **giải mã leetspeak** (`1gn0re`, `b0 qu4`; không đụng vào số và giá tiền) |
| L1 Signatures | **Xong** (xem [layer0_layer1_report_vi.md](layer0_layer1_report_vi.md)): regex EN+VI (cứng, mềm, gợi ý) + chỉ mục ngữ nghĩa đa ngữ trong bộ nhớ (MiniLM, thay ChromaDB; engine v3 giữ chỉ mục 3.590 câu dựng từ dataset v2), ngưỡng chọn trên 3 tập dev. Tập test dataset_v2: chặn đúng 90.5%, chặn nhầm 0.37%; dữ liệu của tác giả khác: 68.8% và 3.8% (mẫu nhỏ). Độ trễ chat p50 13 đến 38 ms. Còn yếu: diễn đạt lại không từ khóa, tiếng Việt không dấu + teencode, lệnh giấu trong tài liệu |
| L2 mDeBERTa | **Xong, bản v3b** (từ 02/11/2026; `firewall/classifier.py`): dataset v3 + giao dịch bình thường, ngưỡng 0,6473, chính sách đồng thuận dưới 0,957 (bản v3 ở `artifacts_v3`). Giao dịch bình thường bị chặn/giữ 71% → 4%; MSB phản hồi tool 28% → 80%. Pipeline trên tập giữ riêng: deepset 75,3% / chặn nhầm 2,5%; Tensor Trust 97,2%; InjecAgent 86,1%; Gray Swan 93,7%; Dolly chặn nhầm 0,6%. Kém v3 ở deepset, InjecAgent cơ bản, MultiJail tiếng Việt (không đạt tiêu chí recall WP7; chọn vì L4 bù) |
| Hợp đồng chung (P1) | **Xong**: `firewall/types.py` (4 quyết định, `LayerResult`), orchestrator gộp bằng quyết định nghiêm trọng nhất, **fail-closed** (layer degraded hoặc lỗi thì không bao giờ ALLOW), `/health` theo từng layer |
| L3 LLM judge | **Code xong, mặc định tắt** (`firewall/judge.py`): chỉ nhận ca lưng chừng của L2 (0,30–0,992), không bao giờ tự gỡ lệnh chặn. Đo bằng judge thay thế (Haiku) trên deepset: chặn nhầm 2,8% → 1,5%, recall không đổi. Provider miễn phí `local` (transformers) đã thử với Qwen2.5-1.5B (WP8): chặn nhầm tăng 29 → 43 trên 185 prompt biên nên giữ tắt |
| Spotlighting + taint + exposed | **Xong** (`firewall/spotlight.py`, `firewall/session.py`): gỡ phần ẩn, quét từng chunk, cắt riêng câu mang chỉ thị, datamark. Mọi chunk làm phiên **exposed**; chunk bị chặn chắc chắn làm phiên **tainted**; mỗi chunk lưu điểm rủi ro (WP4) |
| L4 Action Firewall | **Xong lõi** (`firewall/action_gate.py`, `policies.yaml` v2, `firewall/values.py`, `firewall/egress.py`): luật cứng, taint, **an toàn theo nguồn gốc**, **kiểm soát gửi ra ngoài** (email/URL/tin nhắn/chia sẻ tệp; WP3), **điểm rủi ro nội dung** (WP4), ngưỡng xét duyệt, rate limit, hàng đợi REVIEW. InjecAgent: chuyển tiền độc hại 14/17 → 0/17; 204/204 ca đánh cắp dữ liệu bị luật egress chặn. Bộ v4 (AI tổng hợp): 0/44 lệnh tấn công chạy được, độ phiền 40% (trước WP3-WP4: 56%). Chưa có anomaly detector |
| L5 Output Guard | **Xong** (`firewall/output_guard.py`): canary, secret, lặp lại system prompt, PII tiếng Việt/Anh, gỡ link và ảnh mang dữ liệu ra ngoài. Toàn luật, không có NER |
| Session Risk | **Bản luật** (`firewall/turn_risk.py`, WP6): điểm trượt ≥ 0,7 hoặc ≥ 3 lượt lưng chừng liên tiếp → REVIEW và phiên exposed; chưa đo trên hội thoại thật. Anomaly detector L4 chưa làm |
| Trạng thái bền vững | **Xong** (`firewall/state_store.py`, WP10): SQLite khi đặt `FIREWALL_STATE_DB`; mặc định vẫn trong RAM |
| Kiểm thử | 774 đạt, 1 bỏ qua, 1 xfail (lỗi chặn nhầm giao dịch của L2) |
| Kế hoạch tiếp theo | [implementation_plan_v4_vi.md](implementation_plan_v4_vi.md) |

## 7. Quy tắc thiết kế L1 (rút ra từ lần review code tiếng Việt)

L1 là **hard BLOCK**, nên một regex lỏng sẽ chặn khách hàng thật. Lần review đầu cho thấy 7/12 câu hợp lệ bị chặn và chỉ 1/10 câu tấn công diễn đạt khác bị bắt. Quy tắc để tránh lặp lại:

1. **Không nối hai cụm bằng `.*?` không giới hạn.** Dùng khoảng hở trong một câu (`[^.?!\n]{0,40}?`).
2. **Viết regex tiếng Việt một lần, có dấu.** Bản không dấu được sinh tự động từ chính regex đó.
3. **Câu mơ hồ vào nhóm "soft"**: bị bỏ qua nếu câu chứa là câu hỏi (`?` hoặc `có được không`). Ví dụ "đổi mật khẩu không cần OTP" là tấn công khi ra lệnh, là câu hỏi hợp lệ khi hỏi.
4. **Chỉ chặn khi chắc chắn.** Cái mơ hồ để L2 xử lý, không để L1 chặn cứng.
5. **Từ điển teencode chỉ giữ từ không mơ hồ.** Không mở rộng chữ đơn (`k`, `s`, `h`) và từ tiếng Anh (`admin`, `pass`, `otp`).
6. **Không có code nhận diện mock trong production.** Test phải tự dùng dữ liệu hợp lệ. Có test kiểm tra điều này.
7. **Mọi thay đổi regex phải chạy `tests/test_layer1_vi_regression.py`** (14 câu hợp lệ + 14 câu tấn công), và bộ test này phải mở rộng dần thành tập test tiếng Việt chính thức.

## 8. Giới hạn đã biết

- Các con số cũ (recall 99%, AUC 0.9998) **không dùng được**. Số đo hợp lệ của engine v3 chỉ lấy trên tập công khai giữ riêng (mục 6).
- Hiệu năng tiếng Việt chưa đại diện cho tới khi có tập test tiếng Việt do người viết và kiểm tra.
- Kẻ tấn công thích ứng (WP5c, ngân sách 200 lượt, dữ liệu AI tổng hợp): bộ phát hiện bị lách 31%, lệnh tấn công chạy được 75% ở chế độ detection nhưng **0/28** ở chế độ provenance. Độ phiền của mức exposed mới đo trên luồng do AI tổng hợp (40%; dev 33%, test 46%).
- Không xử lý ảnh/âm thanh.
