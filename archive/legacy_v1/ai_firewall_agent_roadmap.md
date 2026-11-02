# Roadmap chi tiết cho AI Coding Agent
## Dự án: AI-Powered Threat Detection for Conversational Agents (AI Firewall MVP)

Roadmap này được thiết kế để đưa từng task cho AI coding agent (Claude Code hoặc tương
tự) thực hiện tuần tự. Mỗi task có: mô tả, file liên quan, input cần có trước, output kỳ
vọng, và acceptance criteria (điều kiện để coi task đã xong). Nguyên tắc: không sang task
tiếp theo khi task hiện tại chưa pass acceptance criteria.

---

## Cách dùng roadmap này

1. Copy nguyên văn một task (bao gồm phần "Prompt gợi ý cho agent") và đưa cho AI coding
   agent trong một phiên làm việc riêng.
2. Sau khi agent code xong, tự chạy test/acceptance criteria của task đó trước khi
   chuyển sang task kế tiếp.
3. Commit sau mỗi task hoàn thành (message dạng `feat: <task id> - <mô tả ngắn>`), để có
   bằng chứng tiến độ theo sprint (yêu cầu bắt buộc của khóa học).
4. Nếu agent code sai hướng, không sửa tay lan man, mà quay lại prompt, bổ sung rõ ràng
   hơn về acceptance criteria rồi chạy lại.

---

## PHASE 0: Environment & Repo Scaffolding (làm trong 1 buổi)

### P0-T1: Khởi tạo repo và cấu trúc thư mục

- File liên quan: toàn bộ cấu trúc thư mục gốc
- Input cần trước: không có
- Output kỳ vọng: repo Git với đầy đủ thư mục rỗng theo cấu trúc đã thống nhất
  (`data/`, `models/`, `firewall/`, `api/`, `frontend/`, `evaluation/`, `docs/`, `tests/`)
- Acceptance criteria: `git status` sạch, `tree -L 2` khớp cấu trúc dự kiến, có
  `requirements.txt` và `.gitignore` (ignore `__pycache__`, `.env`, `*.pkl`, `checkpoint/`)
- Prompt gợi ý cho agent:
  > "Khởi tạo repo Python cho dự án AI Firewall theo cấu trúc thư mục sau: [dán cấu trúc
  > thư mục]. Tạo requirements.txt với fastapi, uvicorn, xgboost, transformers, torch,
  > sentence-transformers, chromadb, pydantic, pandas, scikit-learn, pytest, joblib.
  > Tạo .gitignore chuẩn cho Python + ML project."

### P0-T2: Setup virtual environment và cài dependencies

- Input cần trước: P0-T1
- Output kỳ vọng: venv hoạt động, tất cả package cài thành công
- Acceptance criteria: `python -c "import xgboost, transformers, chromadb"` chạy không lỗi
- Prompt gợi ý: "Tạo virtual environment, cài requirements.txt, xác nhận import được các
  thư viện chính."

### P0-T3: Setup pytest skeleton

- File liên quan: `tests/`, `pytest.ini` hoặc `pyproject.toml`
- Output kỳ vọng: chạy `pytest` không lỗi (dù chưa có test case thật)
- Acceptance criteria: `pytest --collect-only` chạy được, không exception

---

## PHASE 1: Data Pipeline (Sprint 1, Tuần 2-3)

### P1-T1: Script tải dataset public

- File: `data/scripts/download_datasets.py`
- Input cần trước: P0 hoàn thành
- Output kỳ vọng: script tải được ít nhất 2 dataset public liên quan prompt injection
  (ví dụ deepset/prompt-injections trên HuggingFace, hoặc dataset Kaggle tương đương),
  lưu vào `data/raw/`
- Acceptance criteria: chạy script, có file CSV/JSON trong `data/raw/` với ít nhất vài
  nghìn dòng, có cột text và label
- Prompt gợi ý:
  > "Viết script Python tải dataset prompt injection từ HuggingFace datasets (thử
  > deepset/prompt-injections trước, nếu không có thì tìm dataset tương đương), convert
  > sang pandas DataFrame với 2 cột: text, label. Lưu vào data/raw/prompt_injections.csv.
  > In ra số dòng và phân bố label sau khi tải xong."

### P1-T2: Script chuẩn hóa ground truth

- File: `data/scripts/build_ground_truth.py`
- Input cần trước: P1-T1
- Output kỳ vọng: gộp các dataset raw, chuẩn hóa label thành 4 lớp
  `[SAFE, INJECTION_PROMPT, INJECTION_PAYLOAD, PRIVILEGE_ESCALATION]`, loại duplicate,
  xuất `data/processed/ground_truth.csv`
- Acceptance criteria: file output có đủ 4 nhãn (hoặc ít nhất 2 nếu dataset gốc không đủ
  chi tiết, ghi rõ giới hạn này vào Data Audit Report), không có dòng trùng lặp text
- Prompt gợi ý:
  > "Viết script gộp các file trong data/raw/, chuẩn hóa cột label về 4 giá trị: SAFE,
  > INJECTION_PROMPT, INJECTION_PAYLOAD, PRIVILEGE_ESCALATION (nếu dataset gốc chỉ có
  > binary label thì map INJECTION -> INJECTION_PROMPT tạm thời). Loại bỏ duplicate theo
  > text. Xuất data/processed/ground_truth.csv và in thống kê phân bố nhãn."

### P1-T3: Notebook EDA

- File: `evaluation/eda.ipynb`
- Input cần trước: P1-T2
- Output kỳ vọng: notebook có phân bố label, độ dài text, wordcloud hoặc top-keyword theo
  từng nhãn
- Acceptance criteria: notebook chạy hết cell không lỗi, có ít nhất 3 biểu đồ
- Đây là input trực tiếp cho Data Audit Report của báo cáo tiến độ 2.

### P1-T4: Baseline classifier (regex-only)

- File: `firewall/baseline.py`
- Input cần trước: P1-T2
- Output kỳ vọng: classifier chỉ dùng regex, có hàm `predict(text) -> bool`
- Acceptance criteria: có unit test `tests/test_baseline.py` với ít nhất 5 case
  (2 attack rõ ràng, 3 câu bình thường), tất cả pass
- Prompt gợi ý:
  > "Viết firewall/baseline.py chứa class RegexBaseline với method predict(text) trả về
  > True nếu match các pattern injection phổ biến (ignore instructions, system prompt,
  > jailbreak, DAN mode...). Viết kèm test file với 5 test case."

### P1-T5: Evaluate baseline trên ground truth

- File: `evaluation/eval_baseline.py`
- Input cần trước: P1-T4
- Output kỳ vọng: in ra precision/recall/F1 của baseline trên `ground_truth.csv`
- Acceptance criteria: script chạy xong, in được 3 con số, lưu kết quả vào
  `evaluation/results/baseline_metrics.json`
- Đây là con số baseline để so sánh khi có Layer 2/3 sau này (yêu cầu bắt buộc mục 8.3
  của khóa học: "Baseline & Evaluation").

**Checkpoint Sprint 1:** có dataset sạch, baseline chạy được, biết được baseline precision/
recall hiện tại là bao nhiêu. Đây là nội dung nộp cho báo cáo tiến độ lần 1 (Data Source
Plan) và chuẩn bị cho báo cáo tiến độ lần 2.

---

## PHASE 2: Layer 1 - Regex + Vector Prefilter (Sprint 2, Tuần 4)

### P2-T1: Chuẩn bị known jailbreak patterns

- File: `models/layer1_prefilter/jailbreak_patterns.json`
- Input cần trước: P1-T2 (lấy mẫu từ ground truth làm patterns)
- Output kỳ vọng: file JSON chứa 100-300 câu jailbreak mẫu (lấy từ dataset + tự viết
  thêm biến thể)
- Acceptance criteria: file JSON hợp lệ, có ít nhất 100 entries, không trùng lặp

### P2-T2: Build vector DB

- File: `models/layer1_prefilter/build_vector_db.py`
- Input cần trước: P2-T1
- Output kỳ vọng: script encode patterns bằng `all-MiniLM-L6-v2`, nạp vào ChromaDB
  persistent tại `data/chroma_db/`
- Acceptance criteria: chạy script xong, thư mục `data/chroma_db/` có dữ liệu, query thử
  1 câu trả về kết quả có similarity score

### P2-T3: Code Layer1Prefilter class

- File: `firewall/layer1.py`
- Input cần trước: P2-T2
- Output kỳ vọng: class có method `check(text) -> dict` trả về
  `{layer, decision, reason, confidence}` với decision thuộc `[BLOCK, ESCALATE, PASS]`
- Acceptance criteria: `tests/test_layer1.py` có tối thiểu 6 test case (2 BLOCK rõ ràng
  bằng regex, 2 ESCALATE do similarity trung bình, 2 PASS), tất cả pass
- Prompt gợi ý:
  > "Dựa trên file build_vector_db.py đã có, viết firewall/layer1.py implement class
  > Layer1Prefilter theo thiết kế: check regex trước, nếu không match thì check cosine
  > similarity với known patterns trong ChromaDB. Threshold: similarity > 0.85 = BLOCK,
  > 0.60-0.85 = ESCALATE, dưới 0.60 = PASS. Viết kèm 6 test case."

### P2-T4: Đo tốc độ Layer 1

- File: `evaluation/benchmark_latency.py` (phần Layer 1)
- Acceptance criteria: P95 latency của Layer 1 dưới 10ms trên máy dev (ghi lại con số
  thật, không cần đúng chính xác 2ms lý thuyết)

**Checkpoint:** Layer 1 hoạt động độc lập, có test pass, có latency benchmark thật.

---

## PHASE 3: Layer 2 - XGBoost Classifier (Sprint 2, Tuần 5)

### P3-T1: Feature engineering module

- File: `models/layer2_xgboost/features.py`
- Input cần trước: P2-T3 (cần Layer 1 để lấy max_similarity feature)
- Output kỳ vọng: hàm `extract_features(text) -> dict` trả về khoảng 20-30 features
  (syntactic, semantic, structural như đã thiết kế)
- Acceptance criteria: `tests/test_features.py` kiểm tra hàm trả đủ số features mong đợi,
  không có NaN/None với input hợp lệ

### P3-T2: Build feature dataset

- File: `models/layer2_xgboost/build_feature_dataset.py`
- Input cần trước: P3-T1, P1-T2
- Output kỳ vọng: apply extract_features lên toàn bộ ground_truth.csv, xuất
  `data/processed/features.csv`
- Acceptance criteria: file output có số dòng bằng ground_truth.csv, không có cột toàn
  NaN

### P3-T3: Train XGBoost

- File: `models/layer2_xgboost/train.py`
- Input cần trước: P3-T2
- Output kỳ vọng: model train xong, lưu `models/layer2_xgboost/model.pkl`, in ra
  classification report + AUC trên test set
- Acceptance criteria: AUC > 0.75 (mốc tối thiểu để coi model có học được gì đó, không
  phải random). Nếu AUC thấp hơn, quay lại P3-T1 bổ sung features trước khi tiếp tục
- Prompt gợi ý:
  > "Viết script train XGBoost trên data/processed/features.csv, split 80/20 stratified,
  > in classification_report và AUC. Lưu model bằng joblib vào
  > models/layer2_xgboost/model.pkl. Nếu AUC dưới 0.75, gợi ý thêm features nào có thể
  > cải thiện."

### P3-T4: Code Layer2Classifier wrapper

- File: `firewall/layer2.py`
- Input cần trước: P3-T3
- Output kỳ vọng: class load model.pkl, method `check(text) -> dict` trả về
  `{layer, decision, confidence}`
- Acceptance criteria: `tests/test_layer2.py` pass với ít nhất 5 case, so sánh confidence
  hợp lý (attack rõ ràng > 0.7, câu bình thường < 0.3)

### P3-T5: Evaluate Layer 1 + Layer 2 kết hợp, so với baseline

- File: `evaluation/eval_layer2.ipynb`
- Acceptance criteria: notebook show được bảng so sánh precision/recall/F1 giữa
  [Baseline regex] vs [Layer 1 + Layer 2], chứng minh Layer 2 cải thiện rõ rệt so với
  baseline (đây là bằng chứng bắt buộc nộp báo cáo tiến độ 2)

**Checkpoint Sprint 2:** Layer 1 + Layer 2 hoạt động, có evaluation report so với
baseline, đủ nội dung cho báo cáo tiến độ lần 2 (Model Selection Matrix, Baseline &
Evaluation, Metrics v1).

---

## PHASE 4: Layer 3 - DistilBERT Fine-tune (Sprint 3, Tuần 6)

### P4-T1: Chuẩn bị borderline dataset

- File: `data/scripts/build_borderline_set.py`
- Input cần trước: P3-T4
- Output kỳ vọng: chạy Layer 2 trên toàn bộ ground truth, lọc ra các case có confidence
  trong khoảng 0.50-0.85 (borderline zone), xuất `data/processed/ground_truth_layer3.csv`
- Acceptance criteria: file output có ít nhất vài trăm dòng (nếu quá ít, hạ ngưỡng lọc
  xuống 0.40-0.90 để có đủ data train)
- Lý do bước này: Layer 3 chỉ cần học tốt trên vùng borderline, không cần train lại trên
  toàn bộ dataset (tiết kiệm thời gian train đáng kể).

### P4-T2: Fine-tune DistilBERT

- File: `models/layer3_distilbert/train.py`
- Input cần trước: P4-T1
- Output kỳ vọng: model fine-tuned lưu tại `models/layer3_distilbert/checkpoint/`
- Acceptance criteria: eval F1 trên test set > 0.80. Nếu máy không có GPU và train quá
  chậm, dùng Google Colab (free GPU) để train, sau đó tải checkpoint về
- Prompt gợi ý:
  > "Viết script fine-tune DistilBERT (distilbert-base-uncased) cho binary classification
  > trên data/processed/ground_truth_layer3.csv, dùng HuggingFace Trainer API, 3 epochs,
  > batch size 16, eval mỗi epoch, lưu best model theo F1. In classification report cuối
  > cùng."

### P4-T3: Code Layer3Classifier wrapper

- File: `firewall/layer3.py`
- Input cần trước: P4-T2
- Output kỳ vọng: class load checkpoint, method `check(text) -> dict`
- Acceptance criteria: `tests/test_layer3.py` pass với case roleplay/multi-step tinh vi
  (loại attack mà Layer 1-2 hay miss), confidence hợp lý

### P4-T4: Đo latency Layer 3

- Acceptance criteria: P95 latency dưới 50ms trên CPU (nếu vượt nhiều, cân nhắc dùng
  ONNX runtime hoặc model distillation nhỏ hơn, ghi rõ giới hạn này vào Risk Register)

**Checkpoint:** Layer 3 hoạt động, cải thiện được recall trên các case tinh vi so với chỉ
Layer 1-2.

---

## PHASE 5: Layer 4 - Policy Validator + Orchestrator (Sprint 3, Tuần 7)

### P5-T1: Định nghĩa Pydantic schemas cho action types

- File: `firewall/layer4.py`
- Input cần trước: không phụ thuộc layer khác, có thể làm song song với Phase 4
- Output kỳ vọng: ít nhất 2 action schema (ví dụ RefundRequest, DataAccessRequest) với
  validation rule cụ thể
- Acceptance criteria: `tests/test_layer4.py` có case pass và case bị reject đúng như kỳ
  vọng (ví dụ amount vượt quá order_value*1.1 phải bị reject)

### P5-T2: Code Orchestrator ghép 4 layer

- File: `firewall/orchestrator.py`
- Input cần trước: P2-T3, P3-T4, P4-T3, P5-T1 (tất cả layer đã xong)
- Output kỳ vọng: class `FirewallOrchestrator` với method `process_input(text)` chạy đúng
  logic escalation (Layer1 -> nếu ESCALATE -> Layer2 -> nếu borderline -> Layer3), trả về
  decision cuối cùng kèm trace đầy đủ
- Acceptance criteria: `tests/test_orchestrator.py` chạy được toàn bộ 3 kịch bản attack đã
  thảo luận trước đó (thô sơ bị chặn ở Layer 1, phổ biến bị chặn ở Layer 2/3, tinh vi bị
  chặn ở Layer 3), verify trace đúng layer nào xử lý

### P5-T3: End-to-end evaluation

- File: `evaluation/eval_end_to_end.ipynb`
- Input cần trước: P5-T2
- Output kỳ vọng: chạy orchestrator trên toàn bộ eval set, đo precision/recall/F1 toàn
  pipeline, so sánh với baseline và với chỉ-Layer-2
- Acceptance criteria: pipeline đầy đủ (4 layer) có recall cao hơn baseline ít nhất 20
  điểm phần trăm, đây là bằng chứng chính cho phần "AI tạo ra giá trị gì" trong báo cáo

**Checkpoint Sprint 3:** Pipeline 4 layer hoạt động end-to-end, có evaluation report đầy
đủ so với baseline, đủ nội dung cho AI System Card và Evaluation Report.

---

## PHASE 6: API Layer (Sprint 3, Tuần 7, làm song song cuối phase 5)

### P6-T1: Pydantic request/response schemas

- File: `api/schemas.py`
- Output kỳ vọng: `ChatRequest`, `ChatResponse`, `ActionRequest` models

### P6-T2: Endpoint /chat/message

- File: `api/routes/chat.py`
- Input cần trước: P5-T2, P6-T1
- Output kỳ vọng: endpoint nhận text, chạy qua orchestrator, trả JSON kết quả
- Acceptance criteria: test bằng `httpx`/`TestClient`, gọi endpoint với 1 câu attack và
  1 câu bình thường, verify status code 200 và decision đúng

### P6-T3: Endpoint /console/incidents

- File: `api/routes/security_console.py`
- Input cần trước: P6-T2
- Output kỳ vọng: mỗi lần có BLOCK, log vào file/SQLite đơn giản, endpoint trả danh sách
  incident gần nhất
- Acceptance criteria: gọi /chat/message với attack, sau đó gọi /console/incidents, thấy
  incident vừa tạo xuất hiện trong response

### P6-T4: WebSocket cho real-time update (tùy chọn, cắt nếu thiếu thời gian)

- Xem Phase MVP Scope Cut ở cuối roadmap này trước khi làm task này.

**Checkpoint:** API chạy được bằng `uvicorn api.main:app`, test qua Postman/curl thành
công cho cả luồng bình thường và luồng bị block.

---

## PHASE 7: Frontend Demo (Sprint 4, Tuần 8)

### P7-T1: App Demo (màn trái) - chat UI đơn giản

- File: `frontend/app-demo/`
- Input cần trước: P6-T2 (API đã chạy)
- Output kỳ vọng: Next.js app có ô chat, gọi API `/chat/message`, hiển thị response
  (ALLOW màu xanh, BLOCK màu đỏ kèm lý do)
- Acceptance criteria: chạy `npm run dev`, gõ được 1 câu attack và thấy UI phản hồi đúng

### P7-T2: Security Console (màn phải)

- File: `frontend/security-console/`
- Input cần trước: P6-T3
- Output kỳ vọng: dashboard hiển thị danh sách incident (bảng đơn giản là đủ cho MVP,
  không cần call graph phức tạp ở bản đầu), có nút refresh
- Acceptance criteria: khi App Demo bị block 1 request, refresh Console thấy incident mới

### P7-T3: (Nếu còn thời gian) Visualize đơn giản cho trace 4 layer

- Hiển thị layer nào đã xử lý request (badge/timeline đơn giản), không cần graph phức
  tạp cho MVP

**Checkpoint:** Demo split-screen chạy được trên localhost, đủ để quay video demo.

---

## PHASE 8: Chuẩn bị Demo Scenarios (Sprint 4, Tuần 8-9)

### P8-T1: Viết 3-4 kịch bản attack cụ thể để demo

- Không phải code, mà là chuẩn bị nội dung: mỗi kịch bản có input mẫu, kỳ vọng layer nào
  chặn, và câu chuyện kinh doanh đi kèm (ví dụ kịch bản refund escalation đã thảo luận)

### P8-T2: Quay video demo 3-5 phút

- Theo yêu cầu khóa học mục 5.1: mô tả workflow và kết quả

---

## PHASE 9: Docs (làm song song từ Sprint 1, hoàn thiện ở Sprint 4)

Các file trong `docs/` nên được viết dần theo từng sprint, không dồn hết vào cuối:

| File | Bắt đầu viết khi nào | Hoàn thiện khi nào |
|---|---|---|
| `docs/ai_canvas.md` | Ngay từ đầu (đã có nội dung từ thảo luận) | Sau P5-T3 (có số liệu thật) |
| `docs/project_charter.md` | Ngay từ đầu | Ít thay đổi sau khi chốt |
| `docs/data_audit_report.md` | Sau P1-T3 (EDA) | Sau P4-T1 |
| `docs/risk_register.md` | Ngay từ đầu | Cập nhật liên tục mỗi sprint |
| `docs/ai_system_card.md` | Sau P5-T3 (có metrics thật) | Cuối Sprint 4 |
| `docs/ai_use_disclosure_log.md` | Ngay từ lần đầu dùng AI hỗ trợ | Cập nhật liên tục |

**Lưu ý quan trọng:** Mỗi lần dùng AI agent để code (theo roadmap này), phải ghi 1 dòng
vào `ai_use_disclosure_log.md`: công cụ dùng, task nào, phần nào giữ nguyên/chỉnh sửa.
Đây là yêu cầu bắt buộc chống đạo văn của khóa học, không ghi sẽ bị trừ điểm nặng.

---

## MVP Scope Cut (áp dụng nếu tới Tuần 7 vẫn chưa xong Phase 4-5)

Thứ tự cắt giảm khi thiếu thời gian, cắt từ trên xuống:

1. P6-T4 (WebSocket real-time) -> thay bằng nút refresh thủ công
2. P7-T3 (visualize trace phức tạp) -> thay bằng badge text đơn giản
3. P2-T1 mở rộng thêm patterns -> giữ nguyên bộ patterns ban đầu, không tối ưu thêm
4. Giảm epoch train Layer 3 từ 3 xuống 2 nếu train quá lâu

**Không được cắt trong mọi trường hợp:**
- P3-T3 (train XGBoost) và P4-T2 (fine-tune DistilBERT), đây là phần chứng minh dự án là
  AI project thật sự, không phải rule-based system
- P5-T3 (end-to-end evaluation so với baseline), đây là bằng chứng bắt buộc cho phần
  Evaluation Report của khóa học

---

## Tóm tắt thứ tự thực hiện

```
Phase 0 (setup)
   |
Phase 1 (data + baseline)
   |
Phase 2 (Layer 1) ----+
   |                   |
Phase 3 (Layer 2)      | có thể làm song song với Phase 5-T1
   |                   |
Phase 4 (Layer 3) -----+
   |
Phase 5 (Layer 4 + Orchestrator)
   |
Phase 6 (API)
   |
Phase 7 (Frontend)
   |
Phase 8 (Demo scenarios + video)

Phase 9 (Docs) chạy song song xuyên suốt từ Phase 1 đến hết
```
