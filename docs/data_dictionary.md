# Data Dictionary

Mô tả từng cột của các tệp dữ liệu. Nguồn sự thật cho schema là `COLUMNS` trong `data/scripts/build_dataset_v2.py` và `REQUIRED` trong `data/scripts/validate_vi_test.py`; nếu hai nơi lệch nhau thì code đúng, tài liệu này sai.

## 1. `data/processed/dataset_v2_{train,validation,test}.csv`

Sinh bởi `python data/scripts/build_dataset_v2.py`. Các tệp CSV này nằm trong `.gitignore` (có thể dựng lại từ seed và lệnh trên, kèm `seed` và hash trong `evaluation/results/dataset_v2_audit.json`).

| Cột | Kiểu | Giá trị | Ý nghĩa |
|---|---|---|---|
| `text` | chuỗi | | Văn bản đưa vào mô hình |
| `label_binary` | 0 hoặc 1 | 0 an toàn, 1 tấn công | Nhãn dùng để huấn luyện |
| `label` | chuỗi | `SAFE`, `INJECTION` | Nhãn dạng chữ, tương ứng `label_binary` |
| `lang` | chuỗi | `en`, `vi`, `mixed` | Ngôn ngữ của văn bản. `mixed` gồm tài liệu một ngôn ngữ chèn câu ngôn ngữ kia và văn bản trộn sẵn |
| `source` | chuỗi | `doc_base`, `chat_bank`, `tmdeptrai`, `llm_gen_vi` | Nguồn của văn bản nền (xem mục 4) |
| `attack_type` | chuỗi | `safe`, hoặc một trong 8 loại tấn công | Loại tấn công. Dòng an toàn luôn là `safe` |
| `orig_id` | chuỗi | `doc:`, `chat:`, `tm:`, `docvi:`, `gen:`, `pure:` + mã | Mã của văn bản nền. **Mọi biến thể của cùng một nền có cùng `orig_id` và luôn nằm cùng một split** |
| `template_id` | chuỗi | `<loại>:<ngôn ngữ>:<chỉ số>` hoặc rỗng | Mẫu câu tấn công đã dùng. **Một mẫu chỉ xuất hiện trong đúng một split** |
| `variant` | chuỗi | xem dưới | Cách tạo dòng này từ văn bản nền |
| `split` | chuỗi | `train`, `validation`, `test` | Tập dữ liệu |
| `is_synthetic` | bool | | Có do máy/LLM tạo hay không. Hiện luôn `True` |
| `synthetic_kind` | chuỗi | `base_text`, `template_injection`, `llm_generated`, `translated` | Loại dữ liệu tổng hợp |
| `insert_text` | chuỗi | câu đã chèn, hoặc rỗng | Đúng câu được chèn vào văn bản nền (an toàn hoặc tấn công). Rỗng với `clean`, `raw`, `pure_attack`. Dùng để gắn nhãn theo từng đoạn cắt khi huấn luyện (chỉ đoạn chứa câu này mới là tấn công) |

**`variant`**:

| Giá trị | Nhãn | Nghĩa |
|---|---|---|
| `clean` | 0 | Văn bản nền, không chèn gì |
| `benign_insert` | 0 | Văn bản nền + một câu vô hại, cùng vị trí và độ dài gần bằng câu tấn công đi kèm |
| `attack_insert_1`, `attack_insert_2` | 1 | Văn bản nền + câu tấn công (hai mẫu khác nhau) |
| `pure_attack` | 1 | Một mẫu tấn công đứng riêng |
| `raw` | 0 hoặc 1 | Dòng LLM sinh sẵn (`tmdeptrai3012`, hoặc `generate_vi.py chat`), giữ nguyên |
| `translated` | 0 hoặc 1 | Dòng dịch từ tiếng Anh sang tiếng Việt bằng LLM, kế thừa `orig_id` của dòng gốc |

**`attack_type`**: `direct_injection`, `prompt_leaking`, `privilege_escalation`, `jailbreak_roleplay`, `action_abuse`, `data_exfiltration`, `subtle_redirect`, `obfuscation` (chỉ có trong dữ liệu `tmdeptrai3012`).

## 2. `data/eval/vi_test_v1.csv` (do nhóm tự viết, xem `docs/vi_test_guide.md`)

| Cột | Giá trị | Ý nghĩa |
|---|---|---|
| `id` | `T001`... | Mã dòng duy nhất |
| `text` | | Câu tiếng Việt |
| `label` | `benign`, `attack` | Nhãn do tác giả gán |
| `attack_type` | `safe` hoặc loại tấn công | |
| `style` | `plain`, `noaccent`, `teencode`, `mixed` | Kiểu viết |
| `difficulty` | `easy`, `hard` | `hard` = câu hợp lệ trông giống tấn công, hoặc tấn công không có từ khóa |
| `author` | tên | Người viết |
| `reviewer` | tên | Người kiểm tra chéo, khác tác giả |
| `reviewer_label` | `benign`, `attack` | Nhãn người kiểm tra tự quyết, trước khi xem nhãn của tác giả |
| `notes` | | Ghi chú, ghi `AI hỗ trợ` nếu có dùng AI |

## 2b. `data/eval/tmdeptrai_external_test.csv`

Phần `test.jsonl` của tác giả `tmdeptrai3012`, **giữ ngoài train**. Cột giống dataset v2 (mục 1), `source = tmdeptrai_test`, `split = external_test`. Dòng trùng với train đã bị loại.

## 2c. Phiếu kiểm tra chéo `data/eval/review/review_<tên>.csv`

Cột: `id`, `text`, `reviewer_label` (người kiểm tra điền `benign` hoặc `attack`), `notes`. Không chứa nhãn của tác giả. `data/eval/vi_test_v1.before_review.csv` là bản gốc trước khi gộp, giữ làm bằng chứng.

## 3. Tệp sinh ra kèm theo

| Tệp | Nội dung |
|---|---|
| `evaluation/results/leakage_report.json` | Kết quả `audit_leakage.py` cho từng nguồn công khai: số dòng, độ dài theo nhãn, AUC độ dài, AUC văn phong, ngôn ngữ lẫn, trùng với deepset, cờ cảnh báo |
| `evaluation/results/dataset_v2_audit.json` | Kết quả dựng dataset v2: số dòng theo split, ngôn ngữ, nguồn; hash; vi phạm cấu trúc; kiểm tra leakage của toàn bộ và từng phần; tỷ lệ mẫu mà regex đã bắt |
| `evaluation/results/vi_test_validation.json` | Kết quả `validate_vi_test.py` |
| `evaluation/results/eda/` | 4 biểu đồ SVG và `eda_report.md` |
| `data/raw/generated_vi/*.jsonl` | Dữ liệu LLM sinh hoặc dịch (`generate_vi.py`), mỗi dòng ghi `provider`, `model`, `prompt_version`, `generated_at` |
| `data/raw/generated_vi/review_sample_*.csv` | 5% (tối thiểu 30 dòng) ngẫu nhiên để người kiểm tra, cột `human_label` để trống |

## 4. Nguồn dữ liệu (`source`)

| Giá trị | Nội dung | Ngôn ngữ nền | Cách tạo |
|---|---|---|---|
| `doc_base` | Ngữ cảnh tài liệu (BIPIA-GPT, chỉ phần an toàn do GPT-4o-mini sinh) hoặc tài liệu tiếng Việt do LLM viết, cộng câu chèn | `en`, `vi` | Tài liệu nền + câu chèn (tấn công hoặc vô hại) từ `data/seeds/` |
| `chat_bank` | Câu hỏi hỗ trợ khách hàng viết tay (24 EN + 24 VI), cộng biến thể chèn câu, cộng 108 tin nhắn tấn công đứng riêng | `en`, `vi` | `data/seeds/benign_bank.json`, `attack_bank.json` |
| `tmdeptrai` | `tmdeptrai3012/prompt-injection-dataset-vi-en`, giữ nguyên, cộng biến thể chèn câu trên phần an toàn của nó | `vi`, `en`, `mixed` | LLM sinh (Gemini, theo mô tả của tác giả) |
| `llm_gen_vi` | Tin nhắn tiếng Việt do `generate_vi.py chat` hoặc `translate` tạo | `vi` | LLM do nhóm chọn |

Seed (`data/seeds/*.json`) do Claude Code soạn ngày 2026-10-13, **chưa được người kiểm tra độc lập**. Ghi vào `docs/ai_use_disclosure_log.md`.
