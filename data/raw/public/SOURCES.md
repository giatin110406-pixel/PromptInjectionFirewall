# Nguồn dữ liệu công khai (bước 0 và 1 của docs/public_data_implementation_plan.md)

Tải ngày 14/10/2026. Mỗi file có SHA-256 trong `hashes.json` (cùng thư mục) để tái lập. Thư mục `data/raw/public/` và `data/eval/public/` nằm trong `.gitignore` (một số nguồn không ghi giấy phép hoặc yêu cầu giữ ghi công); chỉ `SOURCES.md` và `hashes.json` được theo dõi.

| Tập | Nguồn | Giấy phép | Trạng thái |
|---|---|---|---|
| deepset/prompt-injections | https://huggingface.co/datasets/deepset/prompt-injections | Apache-2.0 | Đã tải (train + test) |
| MultiJail | https://huggingface.co/datasets/DAMO-NLP-SG/MultiJail | MIT | Đã tải (315 dòng, 10 ngôn ngữ). Bản tiếng Việt do người chú thích (README: "annotated into nine non-English languages"), README không nói rõ người hay máy dịch |
| InjecAgent | https://github.com/uiuc-kang-lab/InjecAgent (thư mục `data/`) | MIT (file LICENCE) | Đã tải |
| Tensor Trust | https://github.com/HumanCompatibleAI/tensor-trust-data (benchmarks v1, detecting-extractions v1) | **Repo không ghi giấy phép** (API GitHub trả về không có giấy phép) | Đã tải benchmark hijacking và extraction. Chỉ dùng để đo trong nội bộ nhóm, không phân phối lại dữ liệu |
| Gray Swan IPI Arena (bản của bên thứ ba) | https://huggingface.co/datasets/sureheremarv/ipi_arena_attacks | MIT | Đã tải. Đây là upload của người dùng khác, **không phải kênh chính thức của Gray Swan**; chỉ 95 chuỗi tấn công, 28 hành vi. Bài báo: arXiv 2603.15714 |
| databricks-dolly-15k | https://huggingface.co/datasets/databricks/databricks-dolly-15k | CC-BY-SA-3.0 | Đã tải. **Thêm ngoài danh sách ban đầu** để có câu hỏi bình thường do người viết (đo chặn nhầm tiếng Anh) |
| XQuAD, bản tiếng Việt | https://huggingface.co/datasets/google/xquad (xquad.vi) | CC-BY-SA-4.0 | Đã tải. **Thêm ngoài danh sách ban đầu** để có câu hỏi tiếng Việt do người dịch chuyên nghiệp (đo chặn nhầm tiếng Việt) |
| HackAPrompt | https://huggingface.co/datasets/hackaprompt/hackaprompt-dataset | MIT | **Chưa tải được**: gated, yêu cầu tài khoản Hugging Face đồng ý điều khoản. Máy này không có token (HTTP 401). Cần người dùng đăng nhập và đồng ý điều khoản |
| OWASP LLM01 V1 và V2 (PointGuardAI) | https://huggingface.co/datasets/PointGuardAI/Prompt-Injection-OWASP-Benchmark-V2 | "other" (cần đọc điều khoản) | **Chưa tải được**: HTTP 401 khi không đăng nhập. Cần tài khoản Hugging Face và đọc điều khoản |
| AgentDojo | https://github.com/ethz-spylab/agentdojo | Chưa kiểm | **Không dùng**: framework chạy agent, không phải tập văn bản |

Không dùng (đã loại ở bước xét dữ liệu): translated_vi, rikka-snow, SEALSBench, vi-alpaca, Viet4All, Tulu3-vi, Necent, Cogensec, 35.000 dòng BIPIA có chỉ thị.

Tập "mẫu tiếng Việt do nhóm tự viết" chưa có: cần thành viên nhóm viết và duyệt chéo. File mẫu: `data/eval/vi_human_v1_template.csv`.
