### dataset_v2 theo split và ngôn ngữ

| split | en | mixed | vi | tổng |
|---|---|---|---|---|
| train | 5,814 | 2,622 | 1,518 | 9,954 |
| validation | 734 | 298 | 178 | 1,210 |
| test | 620 | 346 | 142 | 1,108 |

### dataset_v2 theo nguồn

| source | train | validation | test | tổng | tấn công | bình thường |
|---|---|---|---|---|---|---|
| chat_bank | 178 | 12 | 36 | 226 | 146 | 80 |
| doc_base | 7,485 | 906 | 869 | 9,260 | 4,520 | 4,740 |
| hard_cases | 442 | 55 | 47 | 544 | 217 | 327 |
| llm_gen_vi | 554 | 60 | 48 | 662 | 376 | 286 |
| tmdeptrai | 1,295 | 177 | 108 | 1,580 | 877 | 703 |

### Chỉ mục ngữ nghĩa của L1 (3,590 mẫu: 1,632 tấn công, 1,958 bình thường)

| origin | mẫu | bản_không_dấu |
|---|---|---|
| attack:chat_bank | 63 | 0 |
| attack:hard_cases | 280 | 107 |
| attack:inserted | 91 | 17 |
| attack:llm_gen_vi | 582 | 268 |
| attack:tmdeptrai | 426 | 150 |
| benign:chat_bank | 45 | 20 |
| benign:document | 507 | 6 |
| benign:hard_cases | 462 | 193 |
| benign:llm_gen_vi | 430 | 190 |
| benign:support_actions | 90 | 30 |
| benign:tmdeptrai | 424 | 167 |
| patterns | 190 | 41 |

### Cửa sổ huấn luyện của L2 (200 token, bước 128; train được cân bằng 1:1)

| split | cửa sổ | tấn công | bình thường |
|---|---|---|---|
| train | 12,244 | 6,122 | 6,122 |
| validation | 2,376 | 723 | 1,653 |
| test | 2,401 | 704 | 1,697 |

### Tập đo riêng (không bao giờ dùng để train)

| tập | dòng | tấn công | bình thường |
|---|---|---|---|
| vi_test_v1 | 300 | 150 | 150 |
| tmdeptrai_external_test | 200 | 100 | 100 |
