# Kế hoạch nội dung BCTĐ2: Data Leakage Check và Baseline

Trạng thái: **bản nháp để duyệt, chưa triển khai**. Lập ngày 15/10/2026. Sau khi duyệt, nội dung được viết thành file docx và đặt trong thư mục này.

Theo file hướng dẫn đồ án (mục 6.2), báo cáo tiến độ 2 có trọng tâm Data + Baseline + Evaluation v1, trong đó có hai hạng mục "Data Leakage Check" và "Baseline model/baseline process". Kế hoạch này chỉ nói về hai hạng mục đó.

## 0. Các câu hỏi cần chốt trước khi viết

| # | Câu hỏi | Đề xuất |
|---|---|---|
| 1 | Báo cáo mô tả dataset nào? | **Dataset v3 và engine hiện chạy** (L1 cũ + L2 v3). Dataset v2 trình bày như "phiên bản trước", vì phần phát hiện leakage chính (BIPIA, deepset) và các số AUC nằm ở đợt làm v2 |
| 2 | Baseline gồm những gì? | Ba mốc: bộ phân loại "ngu" (độ dài và văn phong), regex-only, và model L2 cũ (dataset v2). Mô hình v1 (XGBoost) chỉ thêm nếu còn chạy được (xem mục 2.3) |
| 3 | Độ dài | Khoảng 4 đến 5 trang cho cả hai phần, có 3 bảng và 1 biểu đồ |
| 4 | Tên file | `BCTD2_DataLeakage_Baseline.docx` |

## 1. Phần Data Leakage Check

### 1.1 Dàn ý (thứ tự trình bày)
1. **Định nghĩa trong bài toán này** (2 đến 3 câu): leakage là khi model đoán đúng nhờ tín hiệu không liên quan đến prompt injection. Nêu rõ theo định nghĩa của hướng dẫn ("thông tin không có tại thời điểm dự đoán"): đầu vào của model lúc dự đoán chỉ là văn bản; các cột `source`, `variant`, `lang` không được đưa vào model (đã xác nhận trong `train.py`, chỉ dùng cột `text`); nhãn do cơ chế sinh dữ liệu, không lấy từ kết quả tương lai.
2. **Bảng phương pháp**: sáu loại leakage, mỗi loại có cách kiểm, kết quả và cách xử lý (bảng ở mục 1.2).
3. **Kết quả tóm tắt có số** (bảng "trước và sau": AUC độ dài và văn phong của từng nguồn, của dataset v2 và v3).
4. **Biểu đồ**: cột AUC độ dài và AUC văn phong cho deepset, rikka-snow, BIPIA, tmdeptrai, dataset v2, dataset v3, kèm đường ngưỡng 0,80 và mức nền nhiễu.
5. **Kiểm tra đặc thù cho dữ liệu công khai (v3)**: loại trùng, chia theo câu lệnh, tập giữ riêng.
6. **Giới hạn và rủi ro còn lại** (nói thẳng).
7. **Minh chứng**: danh sách file công cụ và file kết quả.

### 1.2 Sáu loại leakage sẽ trình bày

| Loại | Cách kiểm | Kết quả đã có | Xử lý | Cần số mới? |
|---|---|---|---|---|
| Nguồn gốc quyết định nhãn | Bảng chéo nguồn × nhãn, độ thuần nhất | BIPIA: 1,0 | Loại 35.000 dòng tấn công của BIPIA | Không |
| Độ dài, văn phong | AUC độ dài, AUC văn phong, mức nền nhiễu | deepset 0,81/0,83; rikka-snow 0,82/0,84; BIPIA 0,64/0,71; tmdeptrai 0,59/0,66; dataset v2 0,51/0,51 | Cùng một văn bản nền cho cả hai nhãn, câu chèn khớp độ dài | **Có: chạy `audit_leakage.py` cho dataset v3** (v3 chưa có AUC) |
| Ngôn ngữ | Nhãn theo (split × ngôn ngữ) | Đã sửa ở v2 | Cân bằng nhãn trong từng nhóm | Có: xác nhận lại trên v3 (đã cân bằng tuyệt đối 50/50, cần in bảng) |
| Câu lặp giữa train và test | Mã `orig_id` và `template_id` giữa các split | 0 trùng, có test tự động | Chia theo văn bản nền và theo câu chèn | Có: chạy kiểm trùng gần-giống toàn bộ train với validation và test của v3 |
| Tập test trùng train | Trùng chính xác và gần trùng (TF-IDF ký tự, ngưỡng 0,8) | v3: loại 827 dòng Tensor Trust; tập công khai chỉ 1 dòng trùng dữ liệu dự án | Loại dòng trùng | Không (số đã có trong `dataset_v3_audit.json`, `public_prepare.json`) |
| Rò rỉ khi chọn ngưỡng và đo | Phân vai rõ validation, test, tập giữ riêng | Ngưỡng L2 chọn trên validation; hai mốc L3 chọn trên validation và nửa dev; các tập đầy đủ của Tensor Trust, InjecAgent, Dolly, XQuAD không còn dùng để đo | Chỉ báo kết quả trên tập giữ riêng | Không |

### 1.3 Các phép đo mới cần chạy (ước tính 30 đến 40 phút)
1. `python data/scripts/audit_leakage.py --csv ...` cho dataset v3: AUC độ dài và văn phong cho toàn bộ, theo split và theo từng nguồn, có mức nền nhiễu. Cần kết quả thật (v3 chưa đo) để vẽ biểu đồ "trước và sau".
2. Kiểm trùng gần-giống giữa train với validation và test của v3 (theo từng nguồn), ghi số dòng trùng.
3. Kiểm trùng giữa các tập công khai với nhau (đã nêu là chưa làm), đặc biệt giữa các tập đo và dữ liệu train.
4. In bảng nhãn × (split, ngôn ngữ) của v3 để minh chứng cân bằng.

### 1.4 Giới hạn sẽ nêu thẳng
- Chưa kiểm trùng ngữ nghĩa xuyên ngôn ngữ (cần embedding đa ngữ).
- Văn bản nền BIPIA có thể đã nằm trong dữ liệu huấn luyện của model nền (không kiểm chứng được); nguồn gốc của nó chưa xác minh.
- Validation dùng để chọn ngưỡng nên không phải bằng chứng độc lập.
- deepset vẫn lệch độ dài; chỉ dùng để đo, kèm cảnh báo.
- Câu tấn công tiếng Việt do AI sinh; có thể có lặp cấu trúc giữa train và test ngay cả khi khác từng câu.

## 2. Phần Baseline

### 2.1 Mục tiêu
Chứng minh phần AI (L2 và tổ hợp) có giá trị hơn cách đơn giản, và chỉ ra chỗ nào cách đơn giản đã đủ. Mốc phải được đo **trên cùng các tập sạch** với hệ thống đề xuất.

### 2.2 Các mốc so sánh

| Mốc | Là gì | Vai trò trong báo cáo |
|---|---|---|
| B0. Bộ phân loại "ngu" | Mô hình chỉ nhìn độ dài và văn phong (hồi quy logistic trên đặc trưng hình thức, huấn luyện trên train v3) | "Mốc sàn" và công cụ dò leakage: nếu đạt điểm cao trên một tập thì tập đó bị rò rỉ. Mong đợi gần 0,5 AUC trên tập sạch |
| B1. Regex-only | 63 mẫu viết tay song ngữ trong `firewall/baseline.py` (baseline cũ của dự án: recall 36,93%, precision 100%, F1 53,94% trên 738 mẫu, nay không còn tập đó) | Baseline chính, đúng như `AI Canvas` và Project Charter đã nêu |
| B2. Model L2 cũ (dataset v2) | Model huấn luyện trên dữ liệu AI sinh | "Phiên bản trước" để cho thấy dữ liệu mới giúp gì |
| (B3. Mô hình v1 XGBoost) | Engine cũ trong `archive/legacy_v1/` | Chỉ thêm nếu còn `model.pkl` và chạy được (nhiều khả năng không, vì file bị `.gitignore`) |

Hệ thống đề xuất để so: L1 đầy đủ (regex + chỉ mục), L2 v3 một mình, tổ hợp L1 cũ + L2 v3 (cấu hình đang chạy).

### 2.3 Tập đo và chỉ số
- **Tập đo (đều sạch):** Tensor Trust giữ riêng, InjecAgent giữ riêng, deepset, Gray Swan; Dolly và XQuAD giữ riêng (chặn nhầm); `dataset_v2` test, `tmdeptrai_external` nửa test, `vi_test_v1` nửa test (chỉ ghi là tập cũ có lợi cho model cũ).
- **Chỉ số:** recall, precision, F1, tỷ lệ chặn nhầm (FPR), AUC khi có hai nhãn; khoảng tin cậy 95% (Wilson); tách theo ngôn ngữ và theo loại tấn công khi đủ mẫu.

### 2.4 Phép đo cần chạy
1. Viết `evaluation/eval_baseline_v3.py` (thay `eval_baseline.py` đã hỏng vì trỏ vào file đã xóa): chạy B0, B1 trên tất cả tập ở mục 2.3; B2 và hệ thống đề xuất lấy từ kết quả đã có (`l2_compare.json`, `l1l2_combo.json`) hoặc chạy lại cho cùng điều kiện.
2. Xuất `evaluation/results/baseline_v3.json` làm minh chứng.
3. Kiểm tra khả thi B3; nếu không chạy được thì ghi rõ lý do thay vì bỏ qua.

### 2.5 Dàn ý trình bày
1. Mục tiêu và nguyên tắc (đo trên cùng tập sạch, cùng chỉ số).
2. Mô tả từng mốc.
3. **Bảng so sánh chính:** hàng là tập đo, cột là B0, B1, B2, L1, L2 v3, L1 + L2 (recall / chặn nhầm).
4. Nhận xét: regex đủ ở loại nào (ví dụ chỉ thị có từ khóa rõ), AI cần ở loại nào (chỉ thị trần, tiếng Việt diễn đạt lại), và chỗ nào hệ thống mới còn yếu hơn model cũ (tiếng Việt, tấn công nghiệp vụ, code) kèm số.
5. Liên hệ leakage: B0 gần 0,5 trên tập sạch là bằng chứng hai phần (baseline và leakage) khớp nhau.
6. Giới hạn: baseline chỉ có hai nhãn nhị phân; tập tiếng Việt do người viết chưa có.

## 3. Sản phẩm và các bước thực hiện

| Bước | Việc | Ai | Thời gian ước tính |
|---|---|---|---|
| 1 | Hai bên duyệt kế hoạch này, trả lời mục 0 | Bạn và tôi | - |
| 2 | Chạy các phép đo mới (mục 1.3 và 2.4) | Tôi | 40 đến 60 phút |
| 3 | Dựng biểu đồ AUC trước và sau (mục 1.1 điểm 4) | Tôi | 15 phút |
| 4 | Viết file docx `BCTD2_DataLeakage_Baseline.docx` | Tôi | 30 phút |
| 5 | Bạn đọc, sửa; chốt và đặt vào thư mục `ndung BCTĐ2` | Bạn và tôi | - |

Điểm cần lưu ý khi triển khai: mọi con số trong báo cáo đọc từ file kết quả, không gõ tay; phần nào chưa đo được thì ghi "chưa đo" chứ không ước lượng.
