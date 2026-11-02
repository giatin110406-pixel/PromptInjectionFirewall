# Roadmap triển khai AI Firewall Engine v2

Kiến trúc đích: [docs/engine_architecture_vi.md](docs/engine_architecture_vi.md). Cách engine hoạt động và danh mục tình huống chặn: [docs/engine_how_it_works_vi.md](docs/engine_how_it_works_vi.md).

## Cách dùng roadmap này

1. Mỗi task đưa cho AI coding agent trong một phiên riêng, kèm phần "Prompt gợi ý".
2. Không sang task kế tiếp khi task hiện tại chưa đạt "Tiêu chí hoàn thành".
3. Commit sau mỗi task (`feat: <id> - <mô tả ngắn>`) để có bằng chứng tiến độ theo sprint.
4. Mọi con số trong tài liệu phải do một lệnh chạy lại được tạo ra, ghi kèm dataset hash và git commit. Số nào chưa đo thì ghi "chưa đo".
5. Không mock trong code production. Test dùng model giả nhỏ hoặc provider giả, không dùng nhánh `if mock`.
6. Task đánh dấu 🔒 là việc hủy dữ liệu, cần người xác nhận trước khi chạy.

## Trạng thái hiện tại (đã xong)

- L0 Normalize và regex EN/VI của L1: `firewall/normalize.py`, `firewall/baseline.py`, `firewall/layer1.py`, 28 test hồi quy.
- 93/93 test pass.
- P1-T1, P1-T2 xong: `firewall/types.py`, orchestrator 4 quyết định và fail-closed. P1-T3 chờ P3.
- **L0 + L1 hoàn thiện** (2026-10-13): `firewall/normalize.py`, `firewall/layer1.py`, `firewall/signature_index.py`, `models/layer1_prefilter/build_index.py`, `evaluation/eval_layer1.py`. Báo cáo kết quả, hiệu năng, tình huống: `docs/layer0_layer1_report_vi.md`. 539 test pass.
- P2 trạng thái:
  - **T1 xong**: `data/scripts/audit_leakage.py`, kết quả `evaluation/results/leakage_report.json`.
  - **T2 xong**: `data/scripts/build_dataset_v2.py` + `data/seeds/`, 11,588 dòng, AUC độ dài 0.51 và văn phong 0.52, cân bằng tuyệt đối theo split × ngôn ngữ, chia theo `orig_id` và `template_id`. Tiếng Việt thuần mới 8%.
  - **T3 công cụ xong, dữ liệu chưa có**: `data/scripts/validate_vi_test.py`, `docs/vi_test_guide.md`, `data/eval/vi_test_v1_template.csv`. **Chờ nhóm viết 300 dòng.**
  - **T4 xong** (2026-10-13, DeepSeek): `data/scripts/generate_vi.py` (jobs `chat`, `docs`, `translate`, `verify`; chạy song song), `firewall/llm_provider.py`. Đã sinh 1,666 tin nhắn + 60 tài liệu, kiểm chứng nhãn bằng lượt gọi thứ hai, ghép cặp theo hình thức. Chi tiết và các lỗi đã gặp: `docs/data_audit_report.md` mục 3.5. **Còn:** người kiểm tra tay 5% mẫu; sinh thêm nếu cần.
  - **T5 xong**: `docs/data_audit_report.md`, `docs/data_dictionary.md`, `evaluation/eda.py` (4 biểu đồ SVG; không dùng notebook vì máy chưa cài matplotlib/nbformat).
  - **T6 xong** (2026-10-13, có xác nhận): xóa dữ liệu L3 cũ, rác test, checkpoint trung gian, kết quả eval không hợp lệ, 4 tài liệu v1. Giữ `dataset_for_huggingface.jsonl` và `archive.zip`.
- Chưa xong: P2-T3/T4 (dữ liệu), L2 đa ngữ, L3, spotlighting, L4 nâng cao, L5, Session Risk.

## Hợp đồng chung

Mọi layer trả về cùng một dạng (định nghĩa ở task P1-T1):
- `Decision`: `ALLOW < SANITIZE < REVIEW < BLOCK`; quyết định cuối là cái nghiêm trọng nhất.
- `LayerResult`: `layer, decision, confidence, reason, latency_ms, degraded, details`.
- Trace chỉ **thêm** trường, không đổi tên trường cũ, để API và SOC console cũ vẫn chạy.

## Thứ tự và phụ thuộc

| Phase | Nội dung | Phụ thuộc | Sprint |
|---|---|---|---|
| P1 | Hợp đồng chung, orchestrator 4 quyết định, fail-closed | Không | 2 |
| P2 | Dữ liệu sạch: leakage audit, dataset v2, tập test VI | Không (song song P1) | 2 |
| P3 | L1 index đa ngữ, L2 mDeBERTa, eval toàn pipeline | P2 | 3 |
| P4 | L4 YAML + taint + REVIEW, spotlighting, `/chat/context` | P1 | 3 |
| P5 | L5 Output Guard, Session Risk, L3 judge | P1, P3 | 4 |
| P6 | Anomaly, SOC console, tài liệu với số đo thật | P3-P5 | 4 |

**Nếu thiếu thời gian:** P1 → P2 → P3 → P4. Trong P5 chỉ cần L5 canary; trong P6 chỉ cần REVIEW trên SOC console.

---

## PHASE P1: Hợp đồng chung và orchestrator

### P1-T1: Kiểu dữ liệu dùng chung
- **File**: `firewall/types.py` (mới), `tests/test_types.py`
- **Nội dung**: `Decision` (4 giá trị, có thứ tự), `max_decision()`, `LayerResult`, `Source` (`USER`, `UNTRUSTED`, `SYSTEM`).
- **Tiêu chí**: `max_decision` đúng với mọi tổ hợp; `LayerResult.to_dict()` có đủ trường cũ (`layer`, `decision`, `confidence`, `reason`).
- **Prompt gợi ý**: "Tạo firewall/types.py với enum Decision (ALLOW, SANITIZE, REVIEW, BLOCK có thứ tự), hàm max_decision(*decisions), dataclass LayerResult và enum Source. Viết test cho mọi tổ hợp max_decision."

### P1-T2: Orchestrator 4 quyết định và fail-closed
- **File**: `firewall/orchestrator.py`, `tests/test_orchestrator.py`
- **Nội dung**: giữ `process_input` và `validate_action` (API cũ vẫn chạy); gộp kết quả layer bằng `max_decision`; thêm cờ `degraded` vào trace; **bỏ fallback keyword** ở L3: layer không load được thì `degraded=true` và ca khó → `REVIEW`.
- **Tiêu chí**: 93 test cũ vẫn pass; test mô phỏng model lỗi cho `degraded=true` và `REVIEW`; không có đường nào âm thầm `ALLOW` khi model lỗi.
- **Prompt gợi ý**: "Sửa FirewallOrchestrator dùng Decision/LayerResult. Khi một layer ML không load được, trace ghi degraded=true và các input không qua được L1 chuyển REVIEW. Không mock trong production code."

### P1-T3: Chuyển code cũ vào legacy
- **File**: `firewall/legacy/` (chuyển `layer2.py`, `layer3.py`), `models/layer2_xgboost/`
- **Nội dung**: pipeline chạy thật không import XGBoost và DistilBERT; legacy chỉ dùng trong `evaluation/model_selection.py`.
- **Tiêu chí**: `grep -r "xgboost" firewall/orchestrator.py` rỗng; test cũ liên quan được cập nhật.
- **Lưu ý**: chỉ làm sau khi P3-T3 có L2 thay thế, nếu không pipeline sẽ mất tầng AI. Cho tới lúc đó giữ nguyên cả hai.

---

## PHASE P2: Dữ liệu sạch (chặn mọi việc train)

### P2-T1: Script kiểm tra leakage
- **File**: `data/scripts/audit_leakage.py`, `evaluation/results/leakage_report.json`
- **Nội dung**: với mỗi nguồn (deepset, BIPIA, `tmdeptrai3012`, `dangvansam`, `rikka-snow`, dữ liệu L3 cũ):
  - phân bố độ dài theo nhãn;
  - tỷ lệ lẫn ngôn ngữ (dùng lại `detect_language` trong `data/scripts/vietnamese_norm.py`);
  - tỷ lệ trùng và gần trùng với deepset;
  - **style classifier** chỉ dựa trên n-gram ký tự và độ dài: nếu F1 của nó gần bằng model chính thì có leakage.
- **Tiêu chí**: báo cáo JSON có số liệu từng nguồn; nguồn nào style classifier F1 > 0.9 bị gắn cờ `leaky`; kết quả ghi vào `docs/data_audit_report.md`.
- **Prompt gợi ý**: "Viết data/scripts/audit_leakage.py nhận danh sách nguồn dữ liệu, in và lưu JSON: phân bố độ dài theo nhãn, tỷ lệ lẫn ngôn ngữ, trùng với deepset, và F1 của một logistic regression chỉ dựa trên n-gram ký tự và độ dài (leakage nếu F1 cao)."

### P2-T2: Dataset v2
- **File**: `data/scripts/build_dataset_v2.py`, `tests/test_dataset_v2.py`
- **Schema**: `text, label, lang, source, attack_type, orig_id, split, is_synthetic`.
- **Nội dung**: chia train/val/test **theo `orig_id` trước khi dịch hoặc sinh**; mẫu an toàn và độc hại cùng nguồn và cùng pipeline; cân bằng độ dài giữa hai nhãn; loại nguồn `leaky` hoặc lọc lại. Dùng lại `_records_to_frame` và `deduplicate_and_resolve_conflicts`.
- **Tiêu chí**: không còn nhãn trùng với nguồn; không có `orig_id` nào xuất hiện ở hai split; style classifier trên dataset mới F1 < 0.65; có test tự động cho cả ba điều trên.

### P2-T3: Tập test tiếng Việt (làm tay)
- **File**: `data/eval/vi_test_v1.csv`, `docs/vi_test_guide.md`
- **Nội dung**: 300 câu nhóm tự viết (mỗi người 50, kiểm chéo): ~150 tấn công và ~150 hợp lệ, có dấu, không dấu, teencode, trộn Anh-Việt, ca lưng chừng; mỗi dòng ghi `attack_type`. Mở rộng từ `tests/test_layer1_vi_regression.py`.
- **Tiêu chí**: mỗi mẫu có người thứ hai xác nhận nhãn; câu hợp lệ có độ dài và văn phong tương tự câu tấn công; **không bao giờ dùng để train** (test tự động kiểm tra không trùng với train).

### P2-T4: Dịch và sinh dữ liệu VI
- **File**: `data/scripts/generate_vi.py`, `firewall/prompts/translate_v1.md`, `firewall/prompts/generate_v1.md`
- **Nội dung**: dịch **cả hai nhãn** bằng cùng một prompt (ghi phiên bản vào từng dòng); sinh tấn công theo `attack_type` và câu hỏi chăm sóc khách hàng VI; sinh indirect injection nhúng trong email/tài liệu tiếng Việt. Dùng `JudgeProvider` (xem P5-T3) hoặc API key do nhóm cung cấp; hỗ trợ Ollama cục bộ nếu không có key.
- **Tiêu chí**: 3-5k mẫu dịch + 1-2k mẫu sinh; 100% có `is_synthetic=true` và `orig_id`; tỷ lệ người kiểm tra tối thiểu 5% (ghi vào Disclosure Log).
- **Cần quyết định trước khi làm**: nhóm dùng API key nào hay model cục bộ nào.

### P2-T5: Hoàn thiện Data Audit
- **File**: `docs/data_audit_report.md`, `docs/data_dictionary.md`, `evaluation/eda.ipynb`
- **Nội dung**: Data Dictionary, EDA, Ground Truth Definition, Privacy, Bias, Governance theo mục 8.2 của hướng dẫn môn học. Phần dữ liệu mô phỏng (log tool call, hội thoại nhiều lượt) phải khai báo rõ là mô phỏng.
- **Tiêu chí**: đủ các mục bắt buộc của Data Audit Report; các số liệu khớp `leakage_report.json`.

### P2-T6 🔒: Dọn dữ liệu cũ
- **Nội dung**: xóa `data/processed/ground_truth_layer3.csv`, `real_*.csv`, `ground_truth.csv` (rác hoặc có leakage), các checkpoint trung gian `models/layer3_distilbert/checkpoint/checkpoint-*`, và các file kết quả eval không hợp lệ.
- **Điều kiện**: chỉ làm sau khi P2-T2 tạo xong dataset v2 và người có thẩm quyền xác nhận. Không xóa `dataset_for_huggingface.jsonl` và `archive.zip`.

---

## PHASE P3: L1 đa ngữ, L2 mDeBERTa, đánh giá

### P3-T1: Index chữ ký đa ngữ thay ChromaDB
- **File**: `firewall/signature_index.py` (mới), `models/layer1_prefilter/build_index.py`, `firewall/layer1.py`
- **Nội dung**: embedding `intfloat/multilingual-e5-small`; index numpy trong RAM; kho mẫu từ `models/layer1_prefilter/jailbreak_patterns.json` cộng mẫu VI. Giữ ngưỡng 0.85/0.60 và điều kiện "tín hiệu bảo mật" của `has_security_cue`. Layer 1 không còn import chromadb.
- **Tiêu chí**: câu VI cùng nghĩa với mẫu EN đã biết đạt similarity cao hơn so với `all-MiniLM-L6-v2`; test `tests/test_layer1.py` vẫn pass với index giả nhỏ.

### P3-T2: Huấn luyện L2 đa ngữ
- **File**: `models/l2_multilingual/train.py`, `models/l2_multilingual/calibrate.py`, `tests/test_classifier.py`
- **Nội dung**: dùng lại khung HF Trainer của `models/layer3_distilbert/train.py`; base `microsoft/mdeberta-v3-base` (thay thế: Prompt Guard 2); max_len 256; chọn checkpoint theo F1 trên validation; `save_total_limit=1`; temperature scaling lưu `temperature.json`.
- **Đầu vào**: dataset v2 từ P2-T2, **chưa** chứa tập test.
- **Tiêu chí**: F1 validation được báo cùng ECE sau calibrate; model lưu kèm hash dataset.
- **Lưu ý**: train cần GPU (Colab được).
- **Cắt văn bản (đã đo, 2026-10-13)**: tài liệu trung vị 258 token, p90 515 token. Với `max_len=256`, **18% tài liệu tấn công bị cắt mất đúng câu tấn công** nhưng vẫn mang nhãn tấn công (nhiễu nhãn); với 512 còn 2%. Không dùng 256. Cách đúng: chia tài liệu thành đoạn chồng lấp ≤ 256 token và gắn nhãn tấn công **chỉ cho đoạn chứa `insert_text`** (cột đã có trong dataset v2); khớp với cách L2 quét từng chunk khi chạy thật. Checkpoint L3 hiện tại có lỗi `MISMATCH` từ vựng (xem tài liệu how-it-works, mục 6) nên **không dùng làm điểm xuất phát**.

### P3-T3: Classifier runtime
- **File**: `firewall/classifier.py` (mới)
- **Nội dung**: load model và `temperature.json`, trả `p_malicious`; ngưỡng `≥0.90` BLOCK, `≤0.20` ALLOW, còn lại chuyển L3. Fail-closed: thiếu model → `degraded=true`.
- **Tiêu chí**: test với model giả nhỏ (không mock trong production); p95 latency CPU < 50ms ghi bằng lệnh đo; test fail-closed pass.

### P3-T4: Đánh giá toàn pipeline và so sánh model
- **File**: `evaluation/eval_pipeline_v2.py`, `evaluation/model_selection.py`
- **Nội dung**: chạy **toàn pipeline** trên test EN, test VI (`data/eval/vi_test_v1.csv`) và test mixed; báo precision, recall, F1, FPR, tỷ lệ gọi L3, p50/p95 latency; ghi dataset hash và git commit. So sánh: regex baseline, XGBoost (legacy), DistilBERT (legacy), Prompt Guard 2 (EN và bản VI `MinhNghia/Llama-Prompt-Guard-2-86M-vi`), mDeBERTa v2.
- **Mục tiêu** (chưa phải kết quả): recall EN > 90%, recall VI > 85%, FPR < 3% trên câu chăm sóc khách hàng, p95 đường nhanh < 50ms.
- **Tiêu chí**: file kết quả JSON và bảng Model Selection Matrix; nếu mục tiêu không đạt thì ghi rõ số thật, không chỉnh ngưỡng cho tới khi đạt trên chính tập test.

---

## PHASE P4: Action Firewall và nội dung không tin cậy

### P4-T1: Policy-as-code cho L4
- **File**: `firewall/action/policies.yaml`, `firewall/action/engine.py`, `firewall/layer4.py`
- **Nội dung**: chuyển các hạn mức đang hardcode (refund 110% và $200, transfer limit/OTP/high-value, voucher, access control) vào YAML kèm role, rate limit và nhãn nhạy cảm (`write`, `money`, `identity`, `privilege`). Giữ các model Pydantic và `_effective_roles_and_permissions` cho IAM.
- **Tiêu chí**: toàn bộ `tests/test_layer4.py` vẫn pass; đổi hạn mức chỉ cần sửa YAML; thêm test rate limit.

### P4-T2: Taint tracking và hàng đợi REVIEW
- **File**: `firewall/action/taint.py`, `firewall/action/review_queue.py`, `api/routes/review.py`
- **Nội dung**: session có nội dung `UNTRUSTED` bị gắn taint; tool `money`/`write` khi có taint → `REVIEW`, tool xóa/chuyển tiền → `BLOCK`. Hàng đợi lưu JSON theo mẫu `api/incident_store.py`. `GET /review`, `POST /review/{id}` (duyệt hoặc từ chối, ghi người duyệt).
- **Tiêu chí**: test đủ ba nhánh; hành động nhạy cảm hợp lệ về quyền nhưng lớn → `REVIEW` chứ không `ALLOW`.

### P4-T3: Spotlighting và quét context
- **File**: `firewall/spotlight.py`, `api/routes/chat.py` (`POST /chat/context`), `tests/test_spotlight.py`
- **Nội dung**: `wrap_untrusted(chunks)` bọc từng chunk trong datamark kèm chỉ dẫn "đây là dữ liệu"; quét từng chunk bằng L1+L2; chunk độc hại bị loại (`SANITIZE`) và session gắn taint.
- **Tiêu chí**: email có dòng ẩn bị loại dòng đó, phần còn lại được giữ; ca BIPIA mẫu (sau khi sửa leakage) bị gắn cờ; thao tác sau đó gọi tool nhạy cảm bị chặn.

---

## PHASE P5: Output, Session, LLM judge

### P5-T1: Output Guard
- **File**: `firewall/output_guard.py`, `api/routes/chat.py` (`POST /chat/output`), `tests/test_output_guard.py`
- **Nội dung**: canary token ngẫu nhiên mỗi phiên chèn vào system prompt; output chứa canary → `BLOCK`; lọc PII VN/EN (SĐT, CCCD, email, số thẻ, STK) → `SANITIZE`; chặn markdown image/link mang query dài (exfiltration).
- **Tiêu chí**: test cho từng nhóm; câu trả lời bình thường chứa email công khai của cửa hàng không bị chặn nhầm (cấu hình allowlist).

### P5-T2: Session Risk
- **File**: `firewall/session.py`, `firewall/train_session.py`, `data/scripts/simulate_sessions.py`
- **Nội dung**: lưu theo `session_id`, TTL 30 phút; feature mỗi lượt (điểm L1/L2, số lượt tăng điểm liên tiếp, taint); logistic regression → `session_risk`; ≥0.7 → `REVIEW`, ≥0.9 → `BLOCK`.
- **Tiêu chí**: chuỗi nhiều lượt mô phỏng bị bắt; chuỗi bình thường không bị bắt; báo rõ dữ liệu huấn luyện là mô phỏng.

### P5-T3: LLM judge
- **File**: `firewall/judge.py`, `firewall/prompts/judge_v1.md`, `tests/test_judge.py`
- **Nội dung**: `JudgeProvider` (Anthropic, OpenAI hoặc Ollama chọn qua biến môi trường); prompt có phiên bản; timeout 2 giây; trần chi phí mỗi ngày; chỉ nhận ca L2 lưng chừng. Không có provider hoặc hết ngân sách → `REVIEW`.
- **Tiêu chí**: test với provider giả; tỷ lệ gọi L3 < 5% trên tập test; không bao giờ tự `ALLOW` khi judge lỗi.

---

## PHASE P6: Hoàn thiện

### P6-T1: Anomaly detector cho L4
- **File**: `firewall/action/anomaly.py`, `firewall/action/train_anomaly.py`, `data/scripts/simulate_tool_logs.py`
- **Nội dung**: Isolation Forest trên feature tool call (loại tool, số tiền, tần suất, giờ, có taint).
- **Tiêu chí**: số đo trên log mô phỏng, **khai báo là mô phỏng** trong Data Audit và System Card.

### P6-T2: SOC console
- **File**: `frontend/security-console/components/PipelineFlow.jsx`, `IncidentLog.jsx`, trang REVIEW mới
- **Nội dung**: hiển thị 4 quyết định, hàng đợi REVIEW, cờ `degraded`, trace đầy đủ.
- **Tiêu chí**: chạy được 8 kịch bản trong `docs/demo_scenarios.md` qua giao diện.

### P6-T3: Tài liệu và số đo thật
- **File**: `docs/ai_system_card.md`, `docs/risk_register.md`, `docs/ai_canvas.md`, `docs/engine_architecture_vi.md`, `docs/engine_how_it_works_vi.md`, README
- **Nội dung**: thay mọi "chưa đo" bằng số từ `eval_pipeline_v2.py`; đổi trạng thái trong bảng tình huống 📋 → ✅ cho những gì đã làm; cập nhật AI Use Disclosure Log.
- **Tiêu chí**: mọi con số trong tài liệu truy ra được file kết quả và commit; mọi dòng ✅ trong danh mục tình huống có test tương ứng.

### P6-T4: Test danh mục tình huống
- **File**: `tests/test_threat_catalog.py`
- **Nội dung**: mỗi mã T1-T13 trong `docs/engine_how_it_works_vi.md` có ít nhất một ca chặn và một ca hợp lệ gần giống.
- **Tiêu chí**: test pass; tài liệu và code không lệch nhau.

---

## Kiểm thử và xác minh cuối cùng

1. `.venv\Scripts\python -m pytest -q` pass toàn bộ.
2. `python evaluation/eval_pipeline_v2.py` cho số đo trên test EN, VI, mixed.
3. End-to-end: `uvicorn api.main:app`, chạy 8 kịch bản demo qua `/chat/message`, `/chat/context`, `/chat/action`, `/chat/output`; kiểm tra quyết định và trace trên SOC console.
4. Fail-closed: tạm đổi tên thư mục model L2 → `/health` báo `degraded` và ca lưng chừng thành `REVIEW`.
5. Kiểm tra false positive: toàn bộ danh sách "những gì KHÔNG được chặn" (mục 5 của tài liệu how-it-works) vẫn `ALLOW`.

## Ánh xạ sang yêu cầu môn học

| Yêu cầu | Task cung cấp bằng chứng |
|---|---|
| Data Audit, Leakage Check, Ground Truth | P2-T1, P2-T2, P2-T5 |
| Baseline và Metrics v1 | P3-T4 (regex baseline làm mốc so sánh) |
| Model Selection Matrix, Build/Buy | P3-T4 |
| Evaluation (kỹ thuật, rủi ro) | P3-T4, P6-T4 |
| Human oversight, AI Agent controls (mục 9.3) | P4-T1, P4-T2 |
| Risk Register v2, AI System Card | P6-T3 |
| Operationalization (monitoring, rollback) | P1-T2 (degraded), P5-T2, P6-T2 |
| AI Use Disclosure Log | Cập nhật sau mỗi task dùng AI |
