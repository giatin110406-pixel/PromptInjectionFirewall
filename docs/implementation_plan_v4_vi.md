# Implementation plan: Firewall v4, an toàn theo thiết kế

Lập ngày 31/10/2026. Áp dụng cho engine đang chạy (L1 chỉ mục cũ + L2 trained trên dataset v3). Các con số mục tiêu trong tài liệu này là **mục tiêu**, chưa phải kết quả.

---

## 0. Tóm tắt

**Vấn đề cốt lõi.** Mọi lớp bảo vệ hành động của engine v3 đều phụ thuộc vào việc bộ phát hiện (L1/L2) nhận ra tấn công. Taint chỉ được bật khi một chunk bị chặn chắc chắn ([spotlight.py:220-243](../firewall/spotlight.py#L220-L243)). Vì vậy kẻ tấn công nào lách được L2 thì cũng lách được L4. Nghiên cứu gần đây (*The Attacker Moves Second*, 2025) cho thấy các bộ lọc loại này đều bị kẻ tấn công thích ứng vượt qua.

**Hướng v4.** Đổi vai trò của các layer:

| | v3 | v4 |
|---|---|---|
| Ranh giới an toàn | Bộ phát hiện đoán đúng thì mới an toàn | **Nguồn gốc dữ liệu**: nội dung không tin cậy không thể tự kích hoạt hành động nhạy cảm, dù bộ phát hiện có nhận ra hay không |
| Vai trò L1/L2/L3 | Bức tường | **Bộ giảm phiền**: quyết định ca nào tự cho qua, ca nào hỏi người, ca nào chặn hẳn |
| Thước đo | Recall, FPR trên bộ tấn công cố định | Thêm **tỷ lệ tấn công thành công đến hành động**, **độ phiền**, và kết quả trước **kẻ tấn công thích ứng** |

**Ba giai đoạn:**
1. **Giai đoạn A (tuần 1, phục vụ pitch):** taint theo nguồn gốc, nguồn gốc của tham số (bản tối thiểu), bộ đo an toàn và độ phiền, console xác nhận.
2. **Giai đoạn B (tuần 2–3, chất lượng):** kiểm soát kênh gửi ra ngoài, ma trận quyết định có điểm rủi ro, bộ tấn công thích ứng, chat gắn session và Session Risk, judge miễn phí chạy cục bộ.
3. **Giai đoạn C (sau môn học):** L2 v3b, lưu trạng thái bền vững, dữ liệu tiếng Việt thật.

---

## 1. Hiện trạng từng layer và nguyên nhân gốc

Số liệu lấy từ `evaluation/results/` (engine v3, chỉ tập giữ riêng hoặc chưa từng train).

| Thành phần | Trạng thái | Điểm yếu đã đo | Nguyên nhân gốc |
|---|---|---|---|
| L0 Normalize | Xong | Không có số đo riêng | Không |
| L1 Signatures (regex + chỉ mục ngữ nghĩa) | Xong | deepset: chỉ bắt 16% tấn công một mình | Thiết kế chỉ chặn khi chắc chắn; chỉ mục dựng từ dữ liệu AI của v2 |
| L2 mDeBERTa v3 | Xong | vi_test 71% (81% khi ghép L1); **phản hồi tool `msb_tool_resp` 28%** (n=25); chặn nhầm tài liệu code 4,9% | Tấn công tiếng Việt trong train toàn do AI sinh; train không có định dạng phản hồi tool (JSON); thiếu tài liệu code bình thường |
| L3 judge | Có code, **mặc định tắt** | Với Haiku thay thế trên deepset: chặn nhầm 2,8% → 1,5%, recall không đổi | Cần provider trả phí; chưa có provider miễn phí cấu hình sẵn |
| Spotlighting + taint | Xong | Taint chỉ bật khi chunk bị BLOCK chắc chắn | Taint dựa vào **kết quả phát hiện**, không dựa vào **nguồn gốc** |
| L4 Action Firewall | Xong (luật, YAML, taint, REVIEW, rate limit) | InjecAgent base: lệnh chuyển tiền độc hại chỉ bị chặn **3/17**. Không quét context thì luật cứng cho qua **100%** | Payload độc hại trông hoàn toàn hợp lệ; L4 không biết giá trị trong lệnh đến từ đâu |
| L5 Output Guard | Xong (luật) | Chưa đo trước kẻ tấn công thích ứng | Không |
| Session Risk | **Chưa có code** | Không | `/chat/message` không truyền `session_id` vào engine ([chat.py:39](../api/routes/chat.py#L39)) |
| Anomaly detector L4 | **Chưa có code** | Không | Không |
| Đánh giá | Có bộ đo công khai | Chỉ tấn công cố định; không đo độ phiền; vi_test do Claude viết | Không |

Ghi chú: bảng trạng thái ở [engine_architecture_vi.md](engine_architecture_vi.md) mục 6 đã lỗi thời (ghi L2, L3, L5 "chưa làm"). Cập nhật trong WP11.

---

## 2. Nguyên tắc thiết kế v4

1. **Phát hiện chỉ để tham khảo, nguồn gốc mới là căn cứ.** Một hành động nhạy cảm sau khi agent đã đọc nội dung không tin cậy luôn cần ít nhất một bước xác nhận, bất kể L1/L2 nói gì. Đây là nguyên tắc chính của *Design Patterns for Securing LLM Agents* (2025): khi agent đã đọc dữ liệu không tin cậy, dữ liệu đó không được phép kích hoạt hành động hệ trọng.
2. **Giá trị phải đến từ nguồn tin cậy.** Số tài khoản, email người nhận, URL trong một lệnh chỉ được tự động cho qua nếu chúng xuất hiện trong tin nhắn của chính người dùng hoặc trong danh bạ đã lưu. Ý tưởng này gần với cách CaMeL (Google DeepMind) theo dõi luồng dữ liệu.
3. **Không để ba thứ cùng lúc.** Đọc nội dung không tin cậy, chạm dữ liệu nhạy cảm, và gửi ra ngoài: một session không được làm cả ba mà không có người duyệt.
4. **Đo độ phiền song song với độ an toàn.** Một firewall hỏi người ở mọi bước sẽ bị tắt. Mỗi thay đổi phải báo cả hai con số.
5. **Đo trước kẻ tấn công thích ứng**, không chỉ trên bộ tấn công cố định.
6. **Giữ nguyên các cam kết cũ:** fail-closed, quyết định nghiêm trọng nhất thắng, mọi quyết định có trace giải thích được.

---

## 3. Kiến trúc v4

```
                     (tin cậy)                              (không tin cậy)
 Người dùng gõ ──► /chat/message ──┐          Email/Web/RAG/Tool ──► /chat/context
                    L0 ► L1 ► L2   │                                  L0 ► L1 ► L2 ► Spotlight
                         │         │                                        │
                         ▼         ▼                                        ▼
              ┌──────────────────── SESSION STATE (mới) ─────────────────────┐
              │ mức:  clean ──► exposed ──► tainted                          │
              │ trusted_values:   giá trị do người dùng gõ (STK, email, số tiền)│
              │ untrusted_values: giá trị xuất hiện trong nội dung bên ngoài  │
              │ exposure_risk:    điểm L2 cao nhất của các chunk đã đọc       │
              │ turn_risk:        điểm rủi ro theo từng lượt chat (WP6)       │
              └──────────────────────────────┬───────────────────────────────┘
                                             ▼
 Agent gọi tool ──► /chat/action ──► L4: luật cứng ► tainted ► exposed + nguồn gốc tham số
                                        ► egress ► hạn mức ► rate limit ──► ALLOW / REVIEW / BLOCK
                                             ▼
                                Console: thẻ "Chờ xác nhận" kèm chuỗi nguồn gốc
```

Ba mức của session:

| Mức | Khi nào | Ý nghĩa |
|---|---|---|
| `clean` | Chưa đọc nội dung bên ngoài nào | Hành động theo policy thường |
| `exposed` (mới) | Đã đọc ít nhất một chunk qua `/context`, **dù chunk đó sạch** | Hành động nhạy cảm cần giá trị có nguồn tin cậy, nếu không thì REVIEW |
| `tainted` (đã có) | Một chunk bị phát hiện chắc chắn có lệnh | Hành động nhạy cảm bị BLOCK theo `when_tainted` |

---

## 4. Các gói công việc

Mỗi gói ghi: mục tiêu, file thay đổi, thiết kế, test, cách đo, tiêu chí xong, ước lượng. Ước lượng tính theo ngày làm việc của một người.

### WP1: Taint theo nguồn gốc (mức `exposed`) · Giai đoạn A · 1,5 ngày · ✅ xong 31/10/2026

**Mục tiêu:** hành động nhạy cảm sau khi đọc nội dung bên ngoài luôn cần xác nhận, kể cả khi L1/L2 không phát hiện gì.

**Kết quả** (`evaluation/results/public_eval_l4_provenance.json`, 22 câu lệnh InjecAgent chưa từng train, 238 ca ánh xạ được mỗi bản):

| | v3 (`detection`) | v4 (`provenance`) |
|---|---|---|
| Hành động độc hại được thực thi, bản base | 19/238 | **0/238** |
| Lệnh chuyển tiền độc hại được thực thi, bản base | 14/17 | **0/17** (3 bị BLOCK nhờ taint, 14 bị giữ REVIEW nhờ exposed) |
| Bản enhanced | 0/238 | 0/238 (cả 238 bị BLOCK nhờ taint) |

Con số 0 là đúng theo thiết kế, không phải độ chính xác của model. Cái giá là số lần phải hỏi người với luồng hợp lệ, chưa đo được (WP5b). Test: 733 đạt, 1 bỏ qua (trước đó 714).

**File thay đổi:**
- [firewall/session.py](../firewall/session.py): mở rộng `TaintStore`.
  - Thêm `expose(session_id, source, chunk_id, risk)`, `is_exposed()`, `level()` trả về `clean | exposed | tainted`.
  - Giữ `is_tainted()` và `mark()` để code cũ và test cũ không vỡ.
  - `info()` trả thêm danh sách nguồn gây exposed.
- [firewall/orchestrator.py](../firewall/orchestrator.py) `process_context`: với **mọi** chunk có `session_id`, gọi `expose()` kèm điểm L2 cao nhất của chunk. Chunk `suspicious` vẫn gọi `mark()` như cũ. Trả thêm `session_exposed`.
- [firewall/policies.yaml](../firewall/policies.yaml): lên `version: 2`.
  - Thêm khối `exposure: {mode: provenance | detection}`. `detection` tái hiện đúng hành vi v3, dùng để so sánh A/B.
  - Thêm `when_exposed` cho từng action. Mặc định: các lớp money, identity, privilege, data dùng `review`; lớp write dùng `allow`.
  - Thêm `review_by: user | staff`: người dùng tự xác nhận (chuyển tiền của chính họ) hay nhân viên duyệt (cấp quyền).
- [firewall/action_gate.py](../firewall/action_gate.py): thứ tự kiểm tra mới là luật cứng → tainted → **exposed** → luôn duyệt hoặc hạn mức → rate limit. Lý do có dạng `exposed_session:{action}_after_untrusted_content`, `check="exposure"`. Mục REVIEW lưu danh sách nguồn (chunk id, source).
- [api/schemas.py](../api/schemas.py), [api/routes/chat.py](../api/routes/chat.py): `ContextResponse.session_exposed`, `ActionResponse.exposed`, `ActionResponse.provenance`.
- **Chế độ nghiêm ngặt:** biến môi trường `FIREWALL_REQUIRE_SESSION=1` khiến `/context` và `/action` trả lỗi 422 khi thiếu `session_id`. Nếu không có session thì không có exposure, tức là fail-open.

**Test:** `tests/test_action_gate.py`, `tests/test_orchestrator.py`, `tests/test_api.py`:
- clean → ALLOW; exposed → REVIEW; tainted → BLOCK; lớp write khi exposed → ALLOW.
- `mode: detection` cho đúng kết quả của v3.
- Chunk sạch vẫn làm session exposed.
- Session hết hạn TTL thì trở về clean.
- Toàn bộ 714 test cũ vẫn đạt.

**Đo:** thêm `--exposure-mode provenance|detection` vào `evaluation/eval_public_l4.py`. Báo riêng số ca bị BLOCK nhờ bộ phát hiện và số ca bị giữ lại chỉ nhờ exposed.

**Xong khi:** test đạt; trên InjecAgent ánh xạ được, 100% lệnh độc hại thuộc lớp nhạy cảm bị BLOCK hoặc REVIEW ở chế độ `provenance`. Con số này đúng theo thiết kế; phần có ý nghĩa là độ phiền đo ở WP5.

### WP2: Nguồn gốc của tham số · Giai đoạn A (bản tối thiểu) · 1–1,5 ngày · ✅ xong 31/10/2026

**Mục tiêu:** giảm độ phiền của WP1. Khi người dùng tự gõ số tài khoản, lệnh không cần xác nhận thêm. Khi số tài khoản chỉ có trong email, lệnh bị giữ lại.

**Kết quả:** đã làm như thiết kế dưới đây (`firewall/values.py`, `firewall/trusted_book.yaml`, `provenance_fields` trong `policies.yaml`). Test: 774 đạt, 1 bỏ qua, 1 xfail. InjecAgent vẫn 0/238 hành động độc hại được thực thi.

**Phát hiện khi làm WP2 (chưa sửa):** L2 v3 chặn nhầm phần lớn **yêu cầu giao dịch bình thường có kèm số**: chuyển khoản kèm STK, thanh toán hóa đơn kèm mã khách hàng, nạp ví kèm số điện thoại (điểm 0,92–0,99, cả tiếng Việt lẫn tiếng Anh). Model cũ (v2) chặn 3/6 câu thử, v3 chặn 6/6. Hệ quả: luồng "khách gõ STK rồi agent chuyển" thường dừng ngay ở L2, nên WP2 chưa phát huy được ở kênh người dùng cho tới khi sửa dữ liệu L2 (xem WP7). Số liệu này là thử tay trên 9 câu, chưa phải số đo trên tập.

**Thiết kế:**
- File mới `firewall/values.py`, trích giá trị từ văn bản:
  - Số tài khoản (dãy số 6–19 chữ số, cho phép dấu cách và gạch), email, số điện thoại, URL và domain.
  - **Số tiền viết kiểu Việt Nam:** `50 triệu`, `50tr`, `50.000.000đ`, `2 tỷ`, `500k`, `5 trăm nghìn` đều chuẩn hóa thành số nguyên VND. Đây là phần riêng cho tiếng Việt.
  - Chuẩn hóa trước khi so: bỏ khoảng trắng, dấu chấm, dấu gạch; email viết thường.
- `/chat/message` truyền `session_id` vào engine (sửa luôn lỗ hổng ở [chat.py:39](../api/routes/chat.py#L39)). Tin nhắn **được ALLOW** của người dùng ghi giá trị vào `trusted_values`. Tin nhắn bị BLOCK thì không ghi.
- `/context` ghi giá trị của từng chunk vào `untrusted_values` kèm chunk id. Phần này để giải thích trên console, không dùng để cho qua.
- `policies.yaml`: thêm `provenance_fields` cho từng action, ví dụ `transfer_money: [to_account]`, `send_email: [to]`, `refund: [order_id]`.
- Thêm `trusted_book`: danh bạ người nhận đã lưu, đọc từ file cấu hình demo, coi như nguồn tin cậy.
- Quy tắc trong `action_gate`, chỉ áp dụng khi session `exposed` và chưa `tainted`:

| Giá trị trong `provenance_fields` | Quyết định |
|---|---|
| Tất cả có trong `trusted_values` hoặc `trusted_book` | Bỏ yêu cầu xác nhận do exposed, chỉ còn hạn mức và rate limit |
| Có giá trị chỉ thấy trong `untrusted_values` | REVIEW, lý do `value_from_untrusted:{field}:{chunk_id}` |
| Có giá trị không thấy ở đâu (agent tự sinh) | REVIEW, lý do `value_unknown_origin:{field}` |

- **Số tiền** không dùng làm bằng chứng tin cậy một mình, vì các số nhỏ như "100" xuất hiện khắp nơi. Chỉ người nhận hoặc đích đến mới quyết định.

**Test:** `tests/test_values.py` cho bộ trích, đặc biệt các cách viết tiền Việt và STK có dấu cách. Thêm ca trong `test_action_gate.py`: người dùng gõ STK → ALLOW; STK lấy từ email → REVIEW; STK không rõ nguồn → REVIEW; đã tainted thì vẫn BLOCK dù STK do người dùng gõ.

**Xong khi:** độ phiền trên bộ luồng hợp lệ (WP5) giảm rõ so với chỉ có WP1, còn tỷ lệ tấn công thành công đến hành động vẫn bằng 0 trên bộ InjecAgent ánh xạ được.

### WP3: Kiểm soát kênh gửi ra ngoài (egress) · Giai đoạn B · 1 ngày · ✅ xong 02/11/2026

**Mục tiêu:** chặn lộ dữ liệu qua những hành động "được phép", như gửi email hay gọi URL. Đây là chỗ L5 hiện chưa phủ.

- `policies.yaml`: thêm lớp `communicate` (`send_email`, `http_request`, `post_message`, `share_file`) và danh sách `egress_allowlist` gồm domain công ty.
- Trong session exposed: gửi tới người nhận hoặc domain không nằm trong `trusted_values`, `trusted_book` hay allowlist thì REVIEW. Nếu payload còn chứa PII hoặc secret (dùng lại bộ phát hiện của [output_guard.py](../firewall/output_guard.py)) thì BLOCK.
- Ánh xạ lại nhóm `ds` (data stealing) của InjecAgent: các ca này kết thúc bằng `GmailSendEmail` sau khi đọc dữ liệu riêng tư, nhưng hiện được quy về `data_access`. Sau WP3, bước cuối nên được ánh xạ sang `send_email` để đo đúng kênh gửi ra ngoài.
- Nhóm `dh` (direct harm: khóa thông minh, đèn giao thông, GitHub, terminal…) hiện có 136 ca **không ánh xạ được** trong `public_eval_l4.json`, vì firewall chưa có action tương ứng. Có thể thêm lớp `device_control` và `code_exec` nếu muốn đo phần này. Ngoài phạm vi tuần 1.

**Xong khi:** các ca `ds` được ánh xạ sang `send_email` và bị giữ lại; có test cho allowlist và trường hợp PII trong payload.

**Đã làm (02/11/2026):** lớp `communicate` với 4 action `send_email`, `http_request`, `post_message`, `share_file` ([egress.py](../firewall/egress.py), luật cứng trong [layer4.py](../firewall/layer4.py): địa chỉ email hợp lệ, tối đa 20 người nhận, chỉ gọi http(s), cấm địa chỉ nội bộ/localhost/metadata 169.254.x, cấm link công khai). `egress.allowlist` trong `policies.yaml` (domain kèm subdomain, tên kênh). Thứ tự quyết định: **bí mật** (API key, token, canary) gửi ra ngoài allowlist → BLOCK ở mọi phiên; **dữ liệu cá nhân** (SĐT, email, thẻ, CCCD, STK; dùng lại bộ phát hiện của L5) gửi tới người nhận không do khách gõ hoặc lưu, trong phiên exposed → BLOCK (chỉ ở chế độ provenance); người nhận lạ không kèm dữ liệu nhạy cảm → REVIEW như lệnh tiền. 23 test ([test_egress.py](../tests/test_egress.py)). InjecAgent: 544 ca `ds` nay ánh xạ sang `send_email` tới địa chỉ kẻ tấn công nêu trong lệnh (`eval_public_l4.py`); ở chế độ provenance cả **204/204** ca giữ riêng bị **BLOCK bởi luật egress** (trước WP3: bị REVIEW qua `data_access`), chế độ detection 201/204. Console có nhãn cho các action mới.

### WP4: Ma trận quyết định có điểm rủi ro · Giai đoạn B · 1 ngày · ✅ xong 02/11/2026

**Mục tiêu:** dùng L1/L2 để giảm phiền một cách có kiểm soát, thay vì để chúng làm ranh giới an toàn.

`exposure_risk` là điểm L2 cao nhất của các chunk session đã đọc. Ma trận cho lớp money (các lớp khác tương tự, cấu hình trong YAML):

| Mức session | Nguồn gốc giá trị | `exposure_risk` | Quyết định |
|---|---|---|---|
| clean | | | Policy thường |
| exposed | Tin cậy | < `low` (vd 0,30) | ALLOW (theo hạn mức) |
| exposed | Tin cậy | `low` đến ngưỡng L2 | REVIEW (`review_by: user`) |
| exposed | Không tin cậy hoặc không rõ | bất kỳ | REVIEW |
| tainted | bất kỳ | ≥ ngưỡng L2 | BLOCK |

- Ngưỡng `low` chọn trên **bộ luồng hợp lệ dùng làm dev**, không chọn trên bộ đo.
- Bất biến cần có test: điểm L2 **không bao giờ** đưa một ca có giá trị không tin cậy về ALLOW. Bộ phát hiện chỉ được phép làm quyết định nghiêm hơn, không được nới lỏng.

**Đã làm (02/11/2026):** mỗi chunk lưu điểm L2 cao nhất của nó (`risk` trong kết quả quét, [spotlight.py](../firewall/spotlight.py)); `TaintStore.exposure_risk` là giá trị lớn nhất của phiên. Trong phiên exposed, lệnh có mọi người nhận do khách gõ hoặc đã lưu vẫn bị REVIEW (`check: exposure_risk`) khi `exposure_risk ≥ exposure.risk_low`. `risk_low = 0,30`: chọn bằng [choose_risk_low.py](../evaluation/choose_risk_low.py) chỉ trên nửa dev của bộ luồng hợp lệ; 18 luồng dev được xác nhận nhờ nguồn gốc đều có điểm dưới 0,035 nên mọi ngưỡng từ 0,05 đến 0,6 đều không thêm câu hỏi nào, vì vậy giữ mức sàn 0,30 (dưới mức này câu an toàn nhiều hơn tấn công trong dải điểm L2) thay vì 0,05 dễ vỡ. Test bất biến: 48 tổ hợp (nguồn gốc × điểm × chế độ), điểm L2 không bao giờ làm quyết định yếu đi ([test_exposure_risk.py](../tests/test_exposure_risk.py)). Cùng đợt: `data_access` có `provenance_fields: [resource]` (mã hồ sơ do khách gõ thì không hỏi lại; tên chung như `customer_list` vẫn hỏi). Trên bộ v4 (`v4_eval_v3b_wp.json`), độ phiền ở chế độ provenance giảm 56,3% → **39,6%** (dev 33,3%, test 45,8%; luồng người nhận do khách gõ: 24 → 8 bị hỏi), lệnh tấn công chạy được vẫn 0/44. Thay đổi `data_access` làm theo đúng thiết kế WP2, nhưng nó được nhận ra khi xem kết quả trên cả bộ (dev lẫn test), nên phần test không hoàn toàn độc lập.

### WP5: Bộ đánh giá v4 · Giai đoạn A (a, b) + B (c) · 2–3 ngày · 🟡 (a), (b), (c) đã chạy, nhưng trên dữ liệu AI tổng hợp; còn thiếu bộ nhóm tự viết

**(a) Bộ an toàn:** InjecAgent ánh xạ được (base và enhanced), Gray Swan IPI, cộng **40–60 kịch bản agent tiếng Việt** do nhóm tự viết: email hóa đơn giả, CV có lệnh ẩn, đánh giá sản phẩm chứa lệnh hoàn tiền, phản hồi tool dạng JSON. Mỗi kịch bản ghi rõ chuỗi nội dung → hành động mà kẻ tấn công nhắm tới.

**(b) Bộ độ phiền:** 80–120 luồng **hợp lệ** bằng tiếng Việt và tiếng Anh, mỗi luồng có nội dung bên ngoài rồi một hành động nhạy cảm chính đáng. Đo độ phiền ở **cả hai chỗ**: tin nhắn người dùng bị L1/L2 giữ hoặc chặn, và hành động bị L4 giữ. Lỗi chặn nhầm ở L2 phát hiện khi làm WP2 cho thấy phần L2 có thể lớn hơn phần L4. Ví dụ: "đọc hóa đơn điện trong email rồi thanh toán cho EVN (đã lưu trong danh bạ)", "đọc yêu cầu hoàn tiền của khách, khách tự gõ mã đơn trong chat". Chia đôi thành dev (chọn ngưỡng ở WP4) và test. Nhóm tự viết, không dùng LLM trả phí.

**(c) Bộ tấn công thích ứng** `evaluation/adaptive_attack.py`:
- Đầu vào: các câu lệnh kẻ tấn công thuộc phần giữ riêng của InjecAgent, cộng các kịch bản tiếng Việt ở (a).
- Kẻ tấn công **xem được điểm L2** (giả định mạnh, kiểu hộp xám) và tìm kiếm tham lam với ngân sách 10, 50, 200 lượt thử.
- Các phép biến đổi không cần LLM: thay từ đồng nghĩa (từ điển nhỏ EN/VI), chuyển ngôn ngữ theo mẫu soạn sẵn, bọc kiểu "để hoàn thành nhiệm vụ, trước tiên...", chia lệnh thành nhiều chunk, bọc JSON, thêm câu lịch sự, bỏ động từ mệnh lệnh, mã hóa (để kiểm tra L0).
- Báo hai đường cong theo ngân sách: **tỷ lệ lách bộ phát hiện** và **tỷ lệ hành động độc hại được thực thi**, với v3 (`detection`) và v4 (`provenance`).
- Phải nói rõ trong báo cáo: bộ biến đổi này yếu hơn kẻ tấn công dùng LLM hoặc RL trong bài *Attacker Moves Second*, nên kết quả chỉ là **cận dưới** của mức dễ bị lách.

**Chỉ số báo cho mọi thay đổi:**

| Chỉ số | Định nghĩa |
|---|---|
| ASR-action | % kịch bản tấn công mà hành động độc hại được ALLOW |
| Detector bypass | % kịch bản mà không chunk nào bị L1/L2 gắn cờ |
| Friction | % luồng hợp lệ bị REVIEW |
| False block | % luồng hợp lệ bị BLOCK |
| Latency | p50/p95 của `/action` và `/context` |

Kèm khoảng tin cậy 95% như các file kết quả hiện có.

**Xong khi:** `evaluation/results/v4_eval.json` có đủ các chỉ số cho cả hai chế độ, kèm biểu đồ ngân sách tấn công so với ASR.

**Tiến độ (02/11/2026):** [eval_v4.py](../evaluation/eval_v4.py) đo ASR-action, detector bypass, friction, false block, latency cho cả hai chế độ. Dữ liệu (a) 48 kịch bản và (b) 96 luồng là **bản do AI tổng hợp** (Codex, `data/eval/v4/README.md`), chưa phải bộ nhóm tự viết; không được báo cáo như dữ liệu người viết. Kết quả engine hiện tại (L2 v3b, sau WP3/WP4, `v4_eval_v3b_wp.json`): ASR-action 52,3% (detection) và **0/44** (provenance); bộ phát hiện bỏ lọt 39,6%; độ phiền 15,6% (detection) và 39,6% (provenance; dev 33,3%, test 45,8%), chặn nhầm 8,3%, 15,6% luồng dừng ở tin nhắn người dùng. (c) do bên khác làm (H6, OpenAI Codex): [eval_v4_adaptive.py](../evaluation/eval_v4_adaptive.py) + phép biến đổi [adaptive_transforms.py](../evaluation/adaptive_transforms.py), tìm kiếm ưu tiên điểm L2 thấp, 32 kịch bản có chỉ thị × 200 lượt = 6.400 lượt. Bản bàn giao đo trên policy lúc 03:31 (trước `risk_low` và `data_access.provenance_fields`); đã **đo lại trên policy hiện tại** (`v4_eval_v3b_wp.json`, mục `adaptive`; biểu đồ `v4_adaptive_v3b_wp.png`; kiểm định `validate_adaptive_results.py`, khớp policy hiện tại) và ra cùng số liệu. Ngân sách 10/50/200: bộ phát hiện bị lách 28,1% / 28,1% / **31,3%** (n=32); ASR-action chế độ detection 46,4% / 71,4% / **75,0%** (n=28, bỏ 4 ca cấp quyền vốn luôn REVIEW); chế độ provenance **0% ở cả ba mốc** (lớp nhạy cảm 0/24). Đây là cận dưới trên dữ liệu AI tổng hợp với hành động kịch bản hóa, phép biến đổi không dùng LLM, không phải số đo trên agent LLM thật.

### WP6: Chat gắn session và Session Risk · Giai đoạn B · 1,5 ngày · ✅ xong 02/11/2026 (bản luật)

- `process_input(text, session_id=...)` ghi điểm L2 của từng lượt chat vào session.
- `turn_risk`: trung bình trượt có trọng số của điểm L2 các lượt gần nhất, cộng số lượt liên tiếp có điểm nằm trong vùng lưng chừng [0,30; ngưỡng L2).
- Quy tắc ban đầu, **không train**: `turn_risk ≥ 0,7` → REVIEW; có từ 3 lượt lưng chừng liên tiếp trở lên → REVIEW. `turn_risk` cao cũng làm session exposed, để hành động sau đó cần xác nhận.
- Tài liệu kiến trúc hiện ghi Session Risk là "100% AI". Phải sửa cho đúng: bản đầu dùng luật; chỉ train model khi có dữ liệu hội thoại nhiều lượt có nhãn. Dữ liệu này chưa có và nguồn công khai chưa được xác minh.
- Test: chuỗi 5 câu tăng dần mức ép bỏ ràng buộc → REVIEW ở lượt 3–4; hội thoại chăm sóc khách hàng dài bình thường không bị REVIEW.

**Đã làm (02/11/2026):** [turn_risk.py](../firewall/turn_risk.py): mỗi tin nhắn người dùng trong một session ghi điểm L2 (lượt bị L1 chặn trước tính 1,0); `turn_risk` = trung bình có trọng số 0,7^tuổi của 5 lượt gần nhất; dải lưng chừng [0,45; ngưỡng L2). `turn_risk ≥ 0,7` hoặc ≥ 3 lượt lưng chừng liên tiếp → tin nhắn REVIEW (`final_reason: session_risk:...`), phiên thành exposed (nguồn `conversation`), giá trị trong tin nhắn bị giữ không được ghi là "khách tự gõ". Ngưỡng đặt tay, chưa tinh chỉnh trên tập đo. Console tab Phiên hiện điểm trượt và số lượt lưng chừng. Test dùng L2 giả trả điểm soạn sẵn (không viết câu tấn công): chuỗi 0,1 → 0,5 → 0,55 → 0,6 bị giữ ở lượt 4; 12 lượt điểm thấp không bị giữ ([test_turn_risk.py](../tests/test_turn_risk.py), 9 test). Trên bộ v4, độ phiền không đổi (56,3%). Chưa có dữ liệu hội thoại nhiều lượt thật để đo.

### WP7: L2 v3b, sửa đúng ba điểm yếu đã đo · Giai đoạn C · 2–3 ngày, cần Colab · ✅ đã thay model 02/11/2026 (không đạt đủ tiêu chí recall, xem dưới)

| Điểm yếu | Sửa dữ liệu |
|---|---|
| Phản hồi tool 28% | Bọc câu chèn (cả tấn công lẫn bình thường) trong JSON phản hồi tool. Giữ tách biệt với phần giữ riêng của InjecAgent và MSB |
| Chặn nhầm tài liệu code 4,9% | Thêm tài liệu code và README bình thường làm văn bản nền |
| Tiếng Việt miền chăm sóc khách hàng | Thêm lại một phần nhỏ seed tấn công miền chăm sóc khách hàng (đánh đổi với định hướng dữ liệu công khai, cần nhóm quyết định) |
| **Chặn nhầm yêu cầu giao dịch bình thường kèm số** (phát hiện khi làm WP2; ưu tiên cao nhất cho ngữ cảnh ngân hàng) | Thêm yêu cầu giao dịch **bình thường** bằng tiếng Việt và tiếng Anh: chuyển khoản kèm STK, thanh toán hóa đơn kèm mã khách hàng, nạp ví, hoàn tiền kèm mã đơn. Viết cặp đối chứng với cùng khung câu: bản người dùng tự yêu cầu (nhãn bình thường) và bản chèn trong tài liệu kèm chỉ thị cho trợ lý (nhãn tấn công), để model học phân biệt "ai ra lệnh" thay vì "có chữ chuyển tiền" |

**Số đo trước khi sửa** (01/11/2026, `evaluation/eval_transactions.py`, tập `data/eval/transactions_v1.jsonl` gồm 108 câu do Claude viết, không dùng để train):

| Nhóm | L2 v3 (đang chạy) | L2 v2 (cũ) |
|---|---|---|
| Yêu cầu giao dịch bình thường bị chặn hoặc giữ | **37/52 (71%)**: có dấu 20/30, không dấu 9/12, tiếng Anh 8/10 | 21/52 (40%) |
| Câu hỏi về giao dịch bị chặn | 1/8 | 1/8 |
| Tài liệu bình thường có STK bị cắt | 3/20 | 2/20 |
| Tài liệu chèn lệnh chuyển tiền bị bắt | 20/20 | 18/20 |
| Tấn công trực tiếp ở kênh người dùng bị bắt | 8/8 | 8/8 |

Mục tiêu sau khi sửa: yêu cầu giao dịch bị chặn dưới 10%, tài liệu chèn lệnh vẫn bị bắt ít nhất 18/20 (tập nhỏ, khoảng tin cậy rộng).

**Tiến độ (01/11/2026): dữ liệu xong, chờ train.** `data/scripts/build_dataset_v3b.py` giữ nguyên toàn bộ v3 và thêm 833 văn bản nền giao dịch bình thường: 731 tin nhắn (38 mẫu câu tiếng Việt × 14, 14 mẫu tiếng Anh × 10, cộng câu viết tay; 55% có dấu, 25% không dấu, 20% teencode) và 102 tài liệu (hóa đơn, biên lai, sao kê, bảng lương, thông báo tiền phòng hoặc học phí yêu cầu *người đọc* chuyển khoản). Mỗi văn bản nền cho 4 dòng như v3 (sạch, chèn ghi chú vô hại, 2 bản chèn câu tấn công lấy từ Tensor Trust, InjecAgent và bộ AI tiếng Việt sẵn có; **không viết câu tấn công mới**). Mỗi mẫu câu nằm trọn trong train, validation hoặc test (80/10/10). Văn bản giống tập đo `transactions_v1` từ 0,7 trở lên (TF-IDF ký tự) bị loại; bản đầu có 7 câu viết tay trùng mã số với tập đo, đã viết lại. Kết quả: train 22.828 dòng, trong đó 1.227 dòng giao dịch bình thường (trước đó 0) so với 584 dòng tấn công InjecAgent. Gói Colab: `python models/l2_multilingual/make_colab_bundle.py --v3b` → `l2_colab_bundle_v3b.zip`, chạy bằng `colab_train_public.ipynb`, model ra `ai_firewall/l2_artifacts_v3b` trên Drive.

**Kết quả (02/11/2026): đã chuyển sang v3b.** Yêu cầu giao dịch bình thường bị chặn/giữ 37/52 → 2/52; chứng từ chèn lệnh bị bắt 20/20 → 17/20 (tiêu chí ≥ 18: không đạt); tập công khai: deepset 80,2 → 75,3, InjecAgent cơ bản 93,6 → 86,1, MultiJail VI 26,8 → 19,8 (tiêu chí giảm ≤ 2 điểm: không đạt), đổi lại MSB tool response 28 → 80, chặn nhầm InjecAgent 29,4 → 11,8. Nhóm chọn thay vì Layer 4 theo nguồn gốc giữ được 0/44 lệnh tấn công chạy được với cả hai model trên bộ v4 (AI tổng hợp). Chi tiết: `PrepareForBCTĐ2/04_layer2_classifier.md`. Model v3 giữ ở `artifacts_v3`. Việc tiếp: v3c = v3b + dữ liệu H5 để lấy lại recall. **Dataset v3c đã build (02/11/2026)** bằng [build_dataset_v3c.py](../data/scripts/build_dataset_v3c.py): giữ nguyên mọi dòng v3b, thêm 1.360 dòng H5 (AI tổng hợp, chưa có người kiểm nhãn) chia theo `family` 80/10/10 trong từng nhóm tool/CSKH/tiền; độ giống cao nhất với mọi tập đo 0,35 và với v3b 0,33 (TF-IDF ký tự), không cặp nào bị loại (`evaluation/results/dataset_v3c_audit.json`). Train trên Colab: `make_colab_bundle.py --v3c`, notebook `colab_train_public.ipynb` với `TAG = 'v3c'`; đánh giá: `run_l2_candidate.py --tag v3c --old v3b`, rồi `eval_v4.py` và `eval_v4_adaptive.py` với tag v3c. Cùng đợt: `voucher_apply`/`coupon_apply` chuyển `when_exposed: review` với `provenance_fields: [voucher_code]` (4 ca lọt trên bộ v4 đều là voucher).

Sau đó: train lại trên Colab (khoảng 30 phút), chạy lại `calibrate_bands.py`, toàn bộ bộ đo công khai và WP5. Chỉ thay model khi không tệ hơn v3 trên các tập giữ riêng. **Điều kiện tiên quyết** để công bố số liệu tiếng Việt: nhóm tự viết khoảng 300 mẫu test.

### WP8: Judge miễn phí chạy cục bộ · Giai đoạn B · 1 ngày · ✅ đã đo 02/11/2026 (không đạt, giữ tắt)

- [llm_provider.py](../firewall/llm_provider.py) đã hỗ trợ `ollama`. Thử model nhỏ lượng tử hóa 4-bit vừa với RTX 3050 6GB (ví dụ lớp 3B–7B) qua `FIREWALL_JUDGE_PROVIDER=ollama`.
- Đo trên 185 prompt biên của engine mới (`public_l3/`), so với kết quả Haiku thay thế đã có. Ghi lại độ trễ: judge nằm trong đường request, timeout 8 giây.
- Chỉ bật mặc định nếu chặn nhầm giảm mà recall không giảm. Nếu không đạt, giữ judge tắt và ghi rõ trong báo cáo.

**Đã làm (02/11/2026), kết quả: không bật.** Máy chưa cài Ollama, và mình không cài phần mềm hệ thống khi không có người; thay vào đó thêm provider `local` ([llm_provider.py](../firewall/llm_provider.py), `LocalHFProvider`: model Hugging Face chạy ngay trong tiến trình bằng transformers, `FIREWALL_JUDGE_PROVIDER=local`, `LOCAL_LLM_MODEL`). Đo bằng [eval_local_judge.py](../evaluation/eval_local_judge.py) với `Qwen/Qwen2.5-1.5B-Instruct` (fp16, vừa GPU 6 GB; 3B–7B không vừa nếu không lượng tử hóa) trên đúng 185 prompt biên mà Haiku đã trả lời. JSON đọc được 185/185; độ trễ p50 4,0 s, p95 5,3 s (dưới giới hạn 8 s, GPU đang chia với tiến trình khác). Model gần như luôn trả lời "attack": 0 câu bình thường được gọi là lành (18/30 bị gọi là tấn công, còn lại "unsure"). Trên 11 tập: tấn công bị chặn 1.530 → 1.624, nhưng câu bình thường bị chặn **29 → 43** (Haiku: 29 → 20). Chặn nhầm tăng nên theo quy tắc trên, judge vẫn tắt. Lưu ý: 185 prompt được ghi với dải của v3 (0,30–0,992). Kết quả: `evaluation/results/local_judge_qwen2_5-1_5b-instruct.json`.

### WP9: Console và luồng xác nhận · Giai đoạn A · 1–1,5 ngày · ✅ phần code xong 01/11/2026 (chờ kịch bản tấn công cho trang demo)

- Thẻ "Chờ xác nhận" hiển thị **chuỗi nguồn gốc**: email X (chunk 3) → số tài khoản 0123… → lệnh `transfer_money` 50.000.000đ. Có nút Duyệt hoặc Từ chối (dùng `/review/{id}/decision` sẵn có).
- Phân biệt `review_by: user` (người dùng tự xác nhận trong khung chat demo) và `staff` (nhân viên duyệt trên console).
- Trang `/sessions` hiển thị mức clean, exposed, tainted của từng session.
- Đây cũng là phần trình diễn chính cho buổi pitch: kể cả khi khán giả lừa được bot, lệnh vẫn hiện ở trạng thái chờ xác nhận.

**Đã làm (01/11/2026):** thẻ chờ duyệt hiện chuỗi nguồn gốc và nhãn ai xác nhận ([ProvenanceChain.jsx](../frontend/security-console/components/ProvenanceChain.jsx)); tab **Phiên** ([SessionList.jsx](../frontend/security-console/components/SessionList.jsx)); API cho khách tự quyết lệnh `review_by: user` của chính mình, người không phải nhân viên duyệt chỉ thấy lệnh của mình ([chat.py](../api/routes/chat.py), 3 test mới); tài khoản demo `khach_hang`, `nhan_vien`. Trang **`/demo`** ([demo.jsx](../frontend/security-console/pages/demo.jsx)): một firewall, ba bối cảnh (Shop online, Ngân hàng số, Nội bộ doanh nghiệp), nút bật/tắt firewall, ô dán tài liệu để khán giả tự thử, bảng "Firewall đang thấy gì". Kịch bản đọc từ `lib/demo_scenarios.json`; hiện mới có ca hợp lệ, các ca tấn công giao cho bên khác ([handoff_noi_dung_tan_cong_vi.md](handoff_noi_dung_tan_cong_vi.md), H1). Đã chạy qua API thật: 3 ca hợp lệ ALLOW; tài liệu chỉ đổi số tài khoản (không có câu lệnh) qua bộ phát hiện nhưng lệnh chuyển tiền bị REVIEW, khách tự hủy được. Chưa thử trên trình duyệt.

### WP10: Trạng thái bền vững · Giai đoạn C · 1 ngày · ✅ xong 02/11/2026

`TaintStore`, `ReviewQueue` và canary hiện nằm trong RAM: khởi động lại là mất, và không chia sẻ được giữa nhiều process. Chuyển sang SQLite (đủ cho demo và một máy chủ) sau một interface chung. Redis để sau.

**Đã làm (02/11/2026):** [state_store.py](../firewall/state_store.py): bảng SQLite `state(namespace, key, value, updated_at)`, chế độ WAL. Bật bằng biến môi trường `FIREWALL_STATE_DB` (`run_demo.bat` đặt `data/firewall_state.sqlite`, đã thêm vào `.gitignore`); không đặt thì mọi thứ vẫn trong RAM như cũ, để test và bộ đo không dùng chung phiên qua file. `TaintStore`, `ValueLedger`, canary của L5 và `TurnRisk` ghi xuống ngay khi đổi và đọc lại hàng của phiên ở mỗi lần đọc, nên khởi động lại hoặc process thứ hai thấy cùng trạng thái; hết hạn (ttl) cũng xóa bản trên đĩa. Hàng chờ duyệt vốn đã lưu file JSON (plan ghi nhầm là RAM): nay ghi qua file tạm rồi thay thế một bước (không hỏng file khi đang ghi thì tắt), và đọc lại file khi process khác đã ghi. `/health` báo `session_state`. 10 test ([test_state_store.py](../tests/test_state_store.py)).

### WP11: Tài liệu và báo cáo · mỗi giai đoạn · 0,5 ngày mỗi lần

- [engine_architecture_vi.md](engine_architecture_vi.md): cập nhật bảng trạng thái mục 6; thêm nguyên tắc nguồn gốc; sửa mô tả Session Risk.
- [engine_how_it_works_vi.md](engine_how_it_works_vi.md): ví dụ C (email → chuyển tiền) theo luồng v4; cập nhật trạng thái T6, T8, T11, T12.
- `PrepareForBCTĐ2/`: cập nhật ghi chú của layer bị thay đổi (L4, spotlight/taint).
- Báo cáo Word: **sửa trực tiếp** các bảng và mục hiện có, không thêm mục mới.

---

## 5. Lộ trình

| Thời gian | Gói | Kết quả để trình bày |
|---|---|---|
| **Tuần 1** (2/11–6/11) | WP1, WP2 bản tối thiểu, WP5a+b, WP9, WP11 | Slide "chặn chuyển tiền độc hại: 17,6% → 100%, độ phiền X%"; demo xác nhận trên console |
| Tuần 1, nếu còn thời gian | WP5c bản rút gọn (ngân sách 10/50) | Slide "kẻ tấn công thử càng nhiều, bộ lọc càng thủng, nhưng tiền vẫn không đi" |
| **Tuần 2–3** | WP3, WP4, WP5c đầy đủ, WP6, WP8 | Báo cáo v4 đầy đủ |
| **Sau môn học** | WP7, WP10, dữ liệu tiếng Việt do người viết | Engine v4 + L2 v3b |

Thứ tự phụ thuộc: WP1 → WP2 → WP4. WP5a+b chạy song song với WP2 (viết dữ liệu). WP9 cần WP1. WP5c cần WP1 để so sánh hai chế độ.

Mỗi gói kết thúc bằng: toàn bộ test đạt, cập nhật ghi chú BCTĐ2, rồi nhóm quyết định có commit hay không (quy ước: chỉ commit khi một phần đã xong hẳn).

---

## 6. Mục tiêu đo

| Chỉ số | v3 (đã đo) | Mục tiêu v4 |
|---|---|---|
| ASR-action, lớp money, InjecAgent ánh xạ được | 14/17 lệnh chuyển tiền được thực thi | 0% (theo thiết kế). **Đã đạt sau WP1: 0/17** |
| ASR-action trước tấn công thích ứng, ngân sách 200 | Chưa đo | 0% với lớp nhạy cảm. **Đạt (02/11/2026): provenance 0/28** (detection 21/28), dữ liệu AI tổng hợp |
| Friction trên luồng hợp lệ | Chưa đo | ≤ 20% khi có WP2 (WP1 một mình sẽ cao hơn nhiều). **Chưa đạt: 39,6%** (provenance); 30/32 luồng có người nhận lấy từ tài liệu bị hỏi lại theo thiết kế, bỏ nhóm này thì 12,5% |
| False block trên luồng hợp lệ | Chưa đo | ≤ 1%. **Chưa đạt: 8,3%** (8/96, đều do L2 coi tài liệu hợp lệ là tấn công rồi taint; 7/8 tiếng Việt) |
| Chặn nhầm tin nhắn bình thường (Dolly, XQuAD) | 0,6% / 0,8% | Không tăng. **Đạt** (v3b: 0,6% / 0,8%) |
| p95 độ trễ `/action` | Chưa đo riêng | < 10 ms. **Đạt: 6,4 ms** (p50 0,14 ms) |

---

## 7. Rủi ro và giới hạn

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Agent không gửi nội dung bên ngoài qua `/context` | Session không exposed, tức fail-open | `FIREWALL_REQUIRE_SESSION=1`; chế độ `assume_exposed` coi mọi session là exposed trừ khi khai báo rõ; ghi rõ yêu cầu tích hợp trong tài liệu |
| Độ phiền cao với công việc nhiều tài liệu | Người dùng tắt firewall | WP2, WP4, danh bạ tin cậy; báo Friction ở mọi lần đo |
| L2 chặn nhầm yêu cầu giao dịch bình thường kèm số tài khoản | Khách không giao dịch được qua chatbot; WP2 không phát huy ở kênh người dùng | ✅ Đã giảm 71% → 4% bằng v3b (02/11/2026); cái giá là recall giảm ở 3 tập công khai |
| Kẻ tấn công lừa chính người dùng gõ lại số tài khoản | Giá trị trở thành "tin cậy" | Ngoài phạm vi (lừa đảo xã hội); console vẫn hiện chuỗi nguồn để người duyệt thấy |
| Giá trị bị làm rối trong nội dung ("0123 + 456789") | Bộ trích không thấy trong `untrusted_values` | Không ảnh hưởng an toàn: giá trị không có trong `trusted_values` thì vẫn REVIEW. Chỉ ảnh hưởng phần giải thích |
| Tác hại chỉ nằm ở nội dung (trả lời sai, thông tin xấu) mà không có hành động | Cơ chế nguồn gốc không phủ | Vẫn cần L1/L2/L5; nói rõ giới hạn |
| Trạng thái trong RAM | Mất khi khởi động lại | WP10 |
| Bộ tấn công thích ứng tự viết yếu hơn thực tế | Đánh giá quá lạc quan về bộ phát hiện | Gọi rõ là cận dưới; điểm chính là ASR-action không phụ thuộc vào bộ phát hiện |
| vi_test và kịch bản tiếng Việt do nhóm hoặc AI viết | Số liệu tiếng Việt chưa đại diện | Không công bố recall tiếng Việt như kết quả cuối cho tới khi có dữ liệu thật |

---

## 8. Ngoài phạm vi của plan này

Ảnh và âm thanh; anomaly detector bằng Isolation Forest (giữ trong roadmap, chưa có dữ liệu chuỗi tool call thật); thay thế kiểm soát truy cập backend; phát hiện nội dung độc hại kiểu MultiJail (không phải prompt injection).

---

## 9. Tài liệu tham khảo

- Nasr, Carlini và cộng sự, *The Attacker Moves Second: Stronger Adaptive Attacks Bypass Defenses Against LLM Jailbreaks and Prompt Injections*, arXiv 2510.09023, 2025. https://arxiv.org/abs/2510.09023
- Beurer-Kellner và cộng sự, *Design Patterns for Securing LLM Agents against Prompt Injections*, arXiv 2506.08837, 2025. https://arxiv.org/abs/2506.08837
- Debenedetti và cộng sự (Google DeepMind), *Defeating Prompt Injections by Design* (CaMeL), arXiv 2503.18813, 2025. https://arxiv.org/abs/2503.18813
- OpenAI, cập nhật bảo mật ChatGPT Atlas về prompt injection, tháng 12/2025 (tóm tắt: https://cyberscoop.com/openai-chatgpt-atlas-prompt-injection-browser-agent-security-update-head-of-preparedness/)
- Kết quả nội bộ: `evaluation/results/public_eval.json`, `public_eval_l4.json`, `baseline_v3.json`, `guardrails_market.json`, `public_l3/l3_public_eval.json`.
