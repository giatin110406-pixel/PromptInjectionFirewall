# Bản đồ dataset theo layer, engine bản dùng dữ liệu công khai (v3)

Lập ngày 14/10/2026 để viết báo cáo firewall bản mới. Đây là **thiết kế đã chốt và số đếm thật của dataset v3**; phần nào chưa làm xong thì ghi "chưa làm". Hướng: loại bớt dữ liệu AI sinh, huấn luyện L2 bằng dữ liệu công khai do người viết (tiếng Anh) và giữ phần AI sinh tiếng Việt vì không có dữ liệu tiêm lệnh tiếng Việt công khai.

## 0. Trạng thái (cập nhật 14/10/2026, sau khi thay model)

**Engine hiện chạy: L1 cũ (chỉ mục dựng từ `dataset_v2`, 3.590 câu) + L2 mới (huấn luyện trên dataset v3).** Quyết định này dựa trên so sánh trước và sau (`evaluation/results/l1_compare.json`, `l2_compare.json`, `l1l2_combo.json`): chỉ mục L1 dựng từ v3 yếu hơn chỉ mục cũ trên hầu hết các tập trung tính, và tổ hợp L1 cũ + L2 v3 tốt hơn L1 v3 + L2 v3 (tiếng Việt 81,0% so với 72,6%).

| Việc | Trạng thái |
|---|---|
| Dựng dataset v3 (`data/scripts/build_dataset_v3.py` → `data/processed_public/`) | Xong, 0 lỗi kiểm tra cấu trúc |
| Huấn luyện L2 trên v3 (Colab T4, 28 phút, 3 epoch) | Xong. Model nằm ở `models/l2_multilingual/artifacts/` (ngưỡng 0,9119, nhiệt độ 1,9412). Model cũ (dataset v2) giữ ở `artifacts_v2_aigen/` để quay lại |
| L1 | **Giữ chỉ mục cũ.** Chỉ mục v3 (8.707 câu) dựng thử ở `models/layer1_prefilter/index_v3/`, không dùng |
| Chọn lại các mốc phụ thuộc điểm L2 | Xong, chỉ dùng validation của v3 và hai nửa dev (`evaluation/calibrate_bands.py`, kết quả `band_calibration.json`): chính sách đồng thuận (chặn đơn lẻ dưới) 0,98 → **0,992**; judge nhận điểm từ **0,30** đến 0,992 |
| Test | 714 đạt, 1 bỏ qua |
| Đo lại trên engine mới | Đã đo: tập công khai giữ riêng (`public_eval.json`), InjecAgent qua L4 (chỉ 22 câu lệnh chưa từng thấy, `public_eval_l4.json`), L3 trên 185 prompt biên (`public_l3/l3_public_eval.json`). Kết quả của engine cũ nằm ở `evaluation/results/v2_model/` |
| API server (cổng 8000) | Phải khởi động lại để nạp model mới |

## 1. Dataset v3 dùng để huấn luyện (L1 chỉ mục và L2)

Tổng: train 20.382 dòng (10.191 tấn công / 10.191 bình thường), validation 2.814, test 2.736. Cân bằng nhãn trong từng cặp (split, ngôn ngữ). Train theo ngôn ngữ: en 14.184, trộn 2.330, vi 3.868.

Cơ chế (giữ nguyên từ v2): cùng văn bản nền cho cả hai nhãn (clean, benign_insert, attack_insert x2), câu bình thường chèn vào cùng vị trí và độ dài khớp câu tấn công, chia split theo văn bản nền và theo câu chèn. Khác v2: câu chèn lấy từ dữ liệu công khai.

| Nguồn (source) | Train (bt / tấn công) | Valid | Test | Ngôn ngữ | Ai tạo nội dung | Công khai? |
|---|---|---|---|---|---|---|
| dolly_doc (văn bản nền Dolly + câu chèn) | 3.148 / 2.561 | 780 | 742 | en (một phần trộn vi) | Nền: người (nhân viên Databricks, CC-BY-SA-3.0). Câu tấn công chèn: Tensor Trust, InjecAgent (người) và AI tiếng Việt | Có |
| dolly_chat (câu lệnh Dolly + câu chèn) | 3.182 / 2.586 | 684 | 803 | en (một phần trộn vi) | Như trên | Có |
| tensortrust_pure (tấn công trần) | 0 / 1.500 | 187 | 187 | en | Người (người chơi Tensor Trust) | Có, giấy phép không ghi |
| bipia_doc (văn bản nền BIPIA-GPT, 1.000 tài liệu) | 1.606 / 1.287 | 321 | 403 | en (một phần trộn vi) | Nền: nguồn gốc chưa xác minh (nhãn "GPT-4o-mini"). Câu chèn như trên | Một phần |
| xquad_vi_doc (đoạn văn XQuAD tiếng Việt) | 322 / 319 | 121 | 97 | vi (một phần trộn en) | Nền: người dịch (CC-BY-SA-4.0). Câu chèn: tấn công tiếng Việt do AI sinh | Có |
| xquad_vi_chat (câu hỏi XQuAD tiếng Việt) | 1.167 / 1.173 | 519 | 361 | vi (một phần trộn en) | Như trên | Có |
| tmdeptrai (dòng gốc, giữ nguyên) | 257 / 278 | 87 | 48 | en, vi, trộn | **AI** (Gemini sinh), công khai | Có |
| llm_gen_vi (giữ nguyên) | 240 / 314 | 60 | 48 | vi | **AI** (DeepSeek sinh, đã kiểm nhãn) | Không |
| hard_cases (giữ nguyên) | 269 / 173 | 55 | 47 | vi (chủ yếu), en | **AI** (Claude Haiku viết, kiểm nhãn mù) | Không |

Nguồn của **câu tấn công** trong train (10.191 dòng tấn công): Tensor Trust 6.554 (6.343 câu duy nhất trong kho), InjecAgent 551 (31 câu lệnh duy nhất), AI tiếng Việt chèn 2.321, AI giữ nguyên 765 (tmdeptrai 278, llm_gen_vi 314, hard_cases 173). Tức khoảng **70% dòng tấn công do người viết (tiếng Anh)**; toàn bộ tấn công tiếng Việt vẫn do AI sinh.
Nguồn của **câu bình thường**: Dolly (tiếng Anh) và XQuAD (tiếng Việt) do người viết hoặc dịch; một phần tiếng Việt do AI sinh để văn phong không tiết lộ nhãn.

### Đã loại khỏi dữ liệu huấn luyện so với v2

| Bị loại | Kích thước | Lý do |
|---|---:|---|
| Mọi dòng có câu chèn do Claude soạn (`data/seeds/*`: 108 câu tấn công, 66 câu chèn vô hại, 48 câu hỏi hỗ trợ): 7.520 dòng doc_base + 910 dòng tmdeptrai + 194 dòng chat_bank | 8.624 | Do AI viết; thay bằng Tensor Trust, InjecAgent, Dolly, XQuAD |
| 32 câu nền của chat_bank (Claude viết) | 32 | Do AI viết |
| Dữ liệu đã bỏ từ trước: translated_vi (823), verify_disagreed (301), chat_vi chưa lọc (1.666), docs_vi (60), 35.000 dòng BIPIA có chỉ thị, rikka-snow (662), SEALSBench | | Rò rỉ văn phong, nhãn nhiễu hoặc dịch lại của dữ liệu khác |

Không dùng: vi-alpaca, Viet4All, Tulu3-vi (GPT sinh hoặc dịch máy), Necent, Cogensec (nhãn yếu), AgentDojo (framework). Chưa có: HackAPrompt, OWASP LLM01 (cần tài khoản Hugging Face), mẫu tiếng Việt nhóm tự viết.

## 2. Phần giữ riêng từ các nguồn công khai (không bao giờ được train, dùng để đo model mới)

| Tập giữ riêng | Số dòng | Chia theo | Layer đo |
|---|---:|---|---|
| holdout_tensortrust (tấn công) | 396 | Theo văn bản, đã loại bản gần trùng với train (827 dòng validation/test bị loại) | L1, L2, pipeline |
| holdout_injecagent_base và enhanced (tool response) | 391 + 391 (374 tấn công + 17 bình thường mỗi bản) | Theo **câu lệnh của kẻ tấn công**: 22 trên 62 câu nằm trong test, 31 trong train, 9 trong validation | L2, Spotlighting, L4 |
| holdout_dolly_instr, holdout_dolly_doc (bình thường) | 1.000, 300 | Theo bản ghi Dolly | Chặn nhầm L1, L2, Spotlighting |
| holdout_xquad_q, holdout_xquad_doc (bình thường, tiếng Việt) | 128, 27 | Theo đoạn văn XQuAD | Chặn nhầm L1, L2, Spotlighting |

## 3. Tập công khai đo toàn bộ (model mới chưa thấy), đo cả model cũ lẫn model mới

| Tập | Số dòng | Layer đo |
|---|---|---|
| deepset | 662 (263 tấn công / 399 bình thường) | L1, L2, pipeline |
| Gray Swan IPI (bản bên thứ ba) | 95 | L2, Spotlighting |
| MultiJail (ngoài phạm vi prompt injection) | 313 vi + 310 en | L1, L2 (đo phụ) |
| 409 prompt biên công khai | 409 | L3 (judge Haiku thay thế) |

## 4. Tập đo cũ (kiểm tra hồi quy của model mới)

| Tập | Số dòng | Layer đo |
|---|---:|---|
| `dataset_v2` test (cũ, AI sinh) | 1.108 | L1, L2, pipeline, L3 (64 ca), Spotlighting (400 tài liệu), L5 (396 tài liệu, 111 tin nhắn) |
| tmdeptrai_external_test | 200 | L1, L2, L3 |
| vi_test_v1 (Claude viết, chưa kiểm chéo) | 300 | L1, L2, L3 |

## 5. Bảng tổng hợp: layer nào dùng dữ liệu gì

| Layer | Huấn luyện / xây | Chọn ngưỡng | Đo |
|---|---|---|---|
| L0 | Không có | | Vài chục ca thử tay |
| L1 regex | Viết tay, không học | | |
| L1 chỉ mục ngữ nghĩa | **Giữ chỉ mục cũ** (3.590 câu từ train của `dataset_v2` + 149 câu jailbreak + 90 câu hỗ trợ). Chỉ mục dựng từ v3 đã thử và bị loại | Ba ngưỡng cũ (0,65 / 0,10 / 0,63) trên các tập dev của v2 | Mục 2, 3, 4 |
| L2 mDeBERTa | Train của v3 (20.382 dòng → cửa sổ 200 token, cân bằng 1:1) | Validation của v3: checkpoint, nhiệt độ, ngưỡng 0,9119 (FPR ≤ 1%) | Mục 2, 3, 4 |
| L3 judge | Không có (chỉ prompt `judge_v1.md`) | Hai mốc 0,30 và 0,992, chọn trên validation của v3 và hai nửa dev | 185 prompt biên của engine mới (Haiku thay thế); 64 ca và 409 prompt cũ chỉ còn cho model cũ |
| Spotlighting, taint | Không có | | holdout_injecagent, Gray Swan, holdout_dolly_doc, holdout_xquad_doc, 400 tài liệu v2 |
| L4 | Luật và `policies.yaml` | | InjecAgent (ca ánh xạ được) |
| L5 | Luật và canary | | 396 tài liệu, 111 tin nhắn của v2 |

## 6. Hạn chế cần nêu trong báo cáo mới

- Tấn công tiếng Việt trong train vẫn **100% do AI sinh** (Gemini, DeepSeek, Claude Haiku); không có dữ liệu tiêm lệnh tiếng Việt công khai. Dữ liệu tiếng Việt do người chỉ là phần bình thường (XQuAD, người dịch).
- InjecAgent chỉ có 62 câu lệnh duy nhất; train dùng 31 câu, nên khả năng khái quát chỉ được đo trên 22 câu còn lại.
- Tensor Trust là tấn công vào một trò chơi (mật khẩu "Access Granted"), không phải tấn công vào trợ lý khách hàng; giấy phép dữ liệu không được ghi.
- Dolly và XQuAD là câu hỏi và tài liệu, không phải lời nhắn thật của khách hàng.
- Văn bản nền BIPIA-GPT vẫn chưa xác minh nguồn gốc (1.000 tài liệu).
- Dòng tấn công tiếng Việt và tấn công nghiệp vụ là phần model mới yếu hơn model cũ (vi_test: L2 một mình 71,4% so với 92,9%; khi ghép L1 cũ là 81,0%). vi_test và `dataset_v2` test do Claude viết nên có lợi cho model cũ.
- Chặn nhầm tăng trên văn bản code của BIPIA (`dataset_v2` test: 4,9% với L2 một mình, cũ 0,7%).
- Các tập đầy đủ của Tensor Trust, InjecAgent, Dolly, XQuAD không còn dùng để đo engine mới vì đã nằm trong train; chỉ dùng phần giữ riêng.
