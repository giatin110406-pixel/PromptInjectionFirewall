# Layer 3: LLM judge

**Trạng thái: code xong, có test, đã chạy thử thành công với Gemini thật, nhưng số đo đầy đủ vẫn là của một judge thay thế (Claude Haiku) vì lần đo 64 câu với Gemini bị giới hạn hạn mức (HTTP 429).** Mã: `firewall/judge.py`, `firewall/prompts/judge_v1.md`, `GeminiProvider` trong `firewall/llm_provider.py`, hai dải ESCALATE trong `firewall/classifier.py`, nối trong `firewall/orchestrator.py`. Test: `tests/test_judge.py` (43 test). Đo: `PrepareForBCTĐ2/tools/eval_l3_judge.py`, kết quả `results/l3/l3_eval.json`.

## Vì sao judge xử lý hai "mép" của L2, không phải một dải lưng chừng
Điểm của L2 gần như chỉ ở hai cực (gần 0 hoặc gần 1). Trên các tập dev, dải điểm 0,30 đến 0,67 chỉ chứa khoảng 3 tấn công và 3 câu an toàn, nên một judge chỉ nhận dải đó gần như không có việc. Nhưng **các lệnh chặn có điểm 0,67 đến 0,98 chứa nhiều câu chặn nhầm**: trên dataset_v2, nhóm điểm 0,67–0,95 có 25–33% là câu an toàn (so với 0,9% ở nhóm ≥ 0,99). Vì vậy judge nhận hai nhóm:

| Phía | Điểm L2 | Ý nghĩa | Judge trả lời thì |
|---|---|---|---|
| `allow` | 0,30 đến dưới ngưỡng 0,666 | L2 cho qua nhưng sát nút | tấn công (chắc) → **BLOCK**; lành (chắc) → ALLOW; còn lại → **REVIEW** |
| `block` | 0,666 đến dưới 0,98 | L2 chặn nhưng không chắc | tấn công (chắc) → BLOCK; lành (chắc) → **REVIEW** (không bao giờ tự mở khóa thành ALLOW); còn lại → **BLOCK** giữ nguyên. Nếu judge không được hỏi (không tích hộp trong console, hoặc không có judge): → **REVIEW** (chính sách đồng thuận, xem `04`) |

Chắc = độ tự tin ≥ 0,7. Judge chỉ nhận **cửa sổ điểm cao nhất** của L2 (tối đa 1.500 ký tự), không đọc cả tài liệu. Hai dải chỉ được mở khi có judge; không có judge thì L2 quyết định một mình như trước.

## Nguyên tắc an toàn
- **Judge lỗi không bao giờ làm quyết định lỏng hơn.** Không có nhà cung cấp, hết thời gian, trả lời không phải JSON, hết hạn mức ngày: phía `allow` thành REVIEW, phía `block` giữ BLOCK. Các trường hợp này đều gắn `degraded=true` trong trace và `/health`.
- **Judge có thể bị lừa bởi chính nội dung nó đọc**, nên: văn bản nằm giữa hai dòng đánh dấu có mã ngẫu nhiên mới cho mỗi lần gọi (nội dung không thể tự đóng dấu), prompt dặn coi mọi chỉ thị trong văn bản là dữ liệu, bắt trả lời đúng một đối tượng JSON, và judge không có quyền nới BLOCK thành ALLOW.
- Hạn mức gọi mỗi ngày (mặc định 500), bộ nhớ đệm (cùng văn bản không gọi lại), thời gian chờ tối đa 8 giây, không thử lại.
- Không gọi dịch vụ nào nếu chưa đặt khóa. Không dùng DeepSeek.

## Nhà cung cấp hiện dùng: DeepSeek, chỉ khi bấm thủ công trên console
Gemini miễn phí đã hết hạn mức nên judge được chuyển sang DeepSeek (`FIREWALL_JUDGE_PROVIDER=deepseek` trong `.env`, mô hình `deepseek-flash`, tắt chế độ "thinking"). Vì số dư DeepSeek còn ít, **chỉ gọi khi một `security_admin` tích hộp "Cho phép L3 gọi LLM judge" ở tab Thử prompt của console** (request mang `use_judge=true`). Test tự động luôn tắt judge, các đường khác (phòng thử tấn công, chat, agent) không bao giờ bật. Hạn mức 60 lần mỗi ngày. Chưa có số đo chất lượng của judge bằng DeepSeek (chưa gọi để đo, nhằm tiết kiệm); số đo vẫn là của judge thay thế Haiku.

## Cách bật Gemini (miễn phí) khi nhóm có khóa
Trong `.env` (không commit):
```
FIREWALL_JUDGE_PROVIDER=gemini
GEMINI_API_KEY=<khóa từ aistudio.google.com>
# GEMINI_MODEL=gemini-2.5-flash   (đổi nếu tên mô hình thay đổi)
FIREWALL_JUDGE_DAILY_CALLS=500
```
Khởi động lại API; `/health` hiện `layer3: ok, provider: gemini`. Các provider khác có sẵn: `ollama` (chạy local), `anthropic`, `openai`. **`GeminiProvider` mới được test bằng máy chủ giả**; định dạng yêu cầu và tên mô hình chưa kiểm chứng với dịch vụ thật.

## Thử với Gemini thật (khóa Google AI Studio miễn phí của nhóm)
- **Chạy thử 2 câu: đúng cả hai** (một lệnh "ignore all previous instructions" trả `attack` 1,0; một câu "bỏ qua phần giới thiệu" trả `benign` 1,0), mỗi lần gọi mất 1,4 đến 2,5 giây. Khóa nằm trong `.env`, API tự đọc.
- **Chạy đủ 64 câu thất bại một phần: chỉ 18/64 lần gọi có câu trả lời, 46 lần lỗi** (HTTP 429, hết hạn mức của gói miễn phí). Số liệu từ lần chạy này **không dùng được** làm kết quả L3 (file `results/l3/l3_eval_gemini_PARTIAL_46_of_64_failed_429.json` giữ để đối chiếu). Cùng lúc đó, các model khác gặp: tên cũ (`gemini-2.0-flash`, `gemini-2.5-flash-lite`) đã ngừng cho khóa mới, API gợi ý `gemini-3.5-flash-lite` và `gemini-3.8-flash` nhưng lúc thử trả timeout và 503.
- **Điều lần chạy lỗi này chứng minh được** là cơ chế an toàn hoạt động trên lỗi thật: 46 lần judge không trả lời, các quyết định đều rơi về phía an toàn (phía `block` giữ BLOCK, phía `allow` thành REVIEW), không có câu tấn công nào bị judge cho qua.
- Muốn có số đo Gemini thật: chờ hạn mức làm mới (hoặc đặt `GEMINI_MODEL` sang model còn hạn mức) rồi chạy `python PrepareForBCTĐ2/tools/eval_l3_judge.py live`. Công cụ đã sẵn, giãn cách 4 giây giữa các lần gọi; gói miễn phí cần giãn lớn hơn (khoảng 7 giây hoặc hơn).
- Khi demo bằng Gemini miễn phí, một số ca sẽ không được phân xử vì hạn mức; engine vẫn an toàn nhưng sẽ có thêm các ca REVIEW.

## Đo bằng judge thay thế (Claude Haiku, không phải Gemini)
Cách làm: `ManualProvider` ghi lại đúng 64 prompt mà judge sẽ nhận (từ 2.818 văn bản của 6 tập đánh giá, tức 2,3% văn bản vào đến L3). Hai tác tử Haiku trả lời từng prompt mà không nhìn thấy nhãn; câu trả lời được phát lại qua chính mã judge để tính quyết định cuối. Hai dải (0,30 và 0,98) được chọn khi xem phân bố điểm của cả dev và test (xem mục Giới hạn); **kết quả báo cáo trên ba tập test nên đọc là lạc quan**.

| Tập test | Tấn công bị chặn: trước → sau | An toàn bị chặn nhầm: trước → sau | An toàn chuyển REVIEW | Tấn công lọt: sau |
|---|---|---|---|---|
| dataset_v2 test (554 / 554) | 547 → 549 | 8 → 6 | 2 | 5 |
| external (48 / 53) | 48 → 48 | 4 → 3 | 1 | 0 |
| vi_test_v1 (84 / 77) | 78 → 81 | 6 → 4 | 2 | 3 |
| **Cộng 3 tập (686 / 684)** | **673 → 678** | **18 → 13** | **5** | **8** |

Không câu tấn công nào bị judge chuyển sang ALLOW (0/41 tấn công mà judge nhìn thấy được gọi là "lành").

Chất lượng judge trên 64 câu (cả dev và test):
| Phía | Câu | Tấn công đoán đúng | An toàn đoán đúng | Sai | Chưa chắc |
|---|---:|---|---|---|---|
| allow | 14 (7 tấn công, 7 an toàn) | 7/7 | 6/7 | 1 (an toàn bị gọi là tấn công) | 0 |
| block | 50 (34 tấn công, 16 an toàn) | 30/34 | 14/16 | 2 (an toàn bị gọi là tấn công) | 4 |

Tổng cộng 57/64 = 89% đúng, 0 trường hợp gọi tấn công là lành.

## Hiệu năng
Judge thêm một lần gọi mô hình ngôn ngữ cho **khoảng 2,3% văn bản** trong tập đánh giá (tập có 50% là tấn công; với lưu lượng thật phần lớn là câu bình thường, tỷ lệ này dự kiến thấp hơn). Độ trễ phụ thuộc nhà cung cấp, chưa đo với Gemini thật. Các trường hợp còn lại không đổi so với L2.

## Giới hạn (nên ghi thẳng khi báo cáo)
- **Chỉ 64 câu**, nên khoảng tin cậy rất rộng: không kết luận được hơn "hướng đi đúng". Cải thiện tổng cộng là 5 tấn công bị bắt thêm và 5 câu an toàn khỏi bị chặn cứng trên 1.370 văn bản test.
- **Judge thay thế là Claude Haiku**, cùng họ với model đã viết `hard_cases` và `vi_test_v1`, nên số đo có thể lạc quan. Cần chạy lại bằng Gemini thật khi có hạn mức (xem mục trên).
- Judge phía `block` chỉ chuyển câu "lành chắc chắn" sang REVIEW, nên các câu chặn nhầm vẫn còn: 13 câu an toàn bị chặn cứng trên ba tập test (vì L2 rất tự tin ở điểm ≥ 0,98 hoặc vì judge không chắc).
- Các câu tấn công bị L2 cho điểm rất thấp (dưới 0,30) không bao giờ đến judge. Judge không cứu được loại lọt này.
- Độ ổn định của dịch vụ miễn phí thấp (429, 503, timeout đã gặp); chưa đo khả năng judge bị chính câu cần phán xét đánh lừa (chỉ có các biện pháp phòng thủ nêu trên, chưa có bộ tấn công vào judge).
- Hai mốc 0,30 và 0,98 được chọn khi xem bảng phân bố điểm L2 của **cả sáu tập đánh giá cùng lúc (cả dev lẫn test)**, nên các số đo chính sách đồng thuận và judge trên các tập test **không hoàn toàn độc lập với việc chọn mốc** và nên đọc là ước lượng lạc quan. Hai mốc cũng chưa được tối ưu hóa.
