"""
Build dataset v3b: identical to v3, but adds banking-context base texts so the model
sees ordinary transaction requests paired with attack inserts and benign inserts.

Why: v3 flagged 37/52 (71%) ordinary banking requests as attacks
(see docs/implementation_plan_v4_vi.md, WP7). The model never saw "chuyển 1 triệu
cho tài khoản X" as a benign base, only as attack content in InjecAgent tool responses.
Adding banking bases gives the model positive examples of these patterns being harmless.

What changes against v3:
  added    ~120 hand-written banking base texts (Vietnamese + some English), covering
           transfer requests, bill payment, top-up, refund, account queries.
           Each base becomes 4 rows (clean, benign_insert, attack_insert×2).
  kept     everything else from v3 verbatim (same seed, same pools, same split logic).

Output: data/processed_public_v3b/dataset_v2_{train,validation,test}.csv
(same file-name convention, so models/l2_multilingual/train.py --data-dir works)

Usage:
    python data/scripts/build_dataset_v3b.py
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
from typing import Any, Dict, List

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from data.scripts.build_dataset_v2 import (  # noqa: E402
    COLUMNS, SPLITS, _row, apply_transform, balance_labels,
    combine_chat, pick_length_matched, pick_transform, rng_for, split_of,
    validate_dataset,
)
from data.scripts import build_dataset_v3 as v3  # noqa: E402
from data.scripts.build_dataset_v3 import (  # noqa: E402
    Pools, build_chat_rows, build_doc_rows, build_pure_attack_rows,
    dolly_records, injecagent_pool, kept_ai_rows, norm_key, short,
    tensor_trust_pool, xquad_records,
)
from data.scripts import build_dataset_v2 as v2  # noqa: E402
from data.scripts.vietnamese_norm import remove_vietnamese_accents  # noqa: E402

OUT_DIR = os.path.join(BASE_DIR, "data", "processed_public_v3b")
AUDIT = os.path.join(BASE_DIR, "evaluation", "results", "dataset_v3b_audit.json")


# ---------------------------------------------------------------------------
# Banking base texts – ordinary requests a bank customer would send
# These are BENIGN contexts; attack sentences will be inserted from existing pools.
# ---------------------------------------------------------------------------
_BANKING_VI = [
    # transfer requests
    "Mình muốn chuyển 500.000đ sang tài khoản 0451207839 ngân hàng Vietcombank.",
    "Cho mình chuyển 2 triệu cho anh Tuấn số tài khoản 9988776655 VietinBank.",
    "Bạn ơi chuyển giúp mình 1.500.000đ vào tài khoản 0112233445 Agribank nhé.",
    "Mình cần chuyển 3 triệu cho chị Lan, số tài khoản MB Bank là 0099887766.",
    "Chuyển 750k tới tài khoản 8877665544 BIDV cho mình nhé.",
    "Nhờ chuyển 10 triệu sang STK 0012345678 Techcombank giùm tôi.",
    "Giúp mình gửi 250.000đ vào tài khoản 5544332211 TPBank.",
    "Tôi muốn chuyển đúng 4.500.000 đồng cho số tài khoản 1122334455 ACB.",
    "Bạn có thể chuyển 1tr2 cho mình qua số 9900112233 VPBank không?",
    "Cho mình chuyển 800k vào tài khoản OCB 6677889900.",
    # bill payment
    "Đóng tiền điện kỳ tháng 9 giúp mình, mã KH PB1200087431.",
    "Mình cần thanh toán tiền nước tháng này, mã số 8812345678.",
    "Bạn ơi thanh toán hộ mình hóa đơn internet VNPTid 20241001234.",
    "Thanh toán tiền điện với mã hóa đơn EV123456789012 giùm mình.",
    "Giúp tôi trả hóa đơn điện thoại trả sau Viettel số 0912345678.",
    "Cần thanh toán học phí kỳ 1 với mã sinh viên SV20230001.",
    "Thanh toán phí bảo hiểm xe máy với hợp đồng số BH123456.",
    # top-up / wallet
    "Bỏ 150k vào ví MoMo của mình, số ví 0938271604.",
    "Bạn có thể nạp 200.000đ vào tài khoản game của mình, ID: GW99887766?",
    "Nạp thẻ điện thoại Viettel 50k cho số 0912345678.",
    "Mình muốn nạp 500k vào ví ZaloPay liên kết với 0901234567.",
    "Nạp 1 triệu vào VNPay ví của mình, mã ví VP0012345.",
    # refund / hoàn tiền
    "Đơn hàng DH20240512001 bị giao sai, mình cần hoàn tiền.",
    "Tôi muốn hoàn trả đơn hàng OD99887766, vui lòng hoàn tiền về tài khoản gốc.",
    "Yêu cầu hoàn tiền cho đơn hàng #12345678, sản phẩm lỗi.",
    "Bạn ơi đơn ORD-2024-99001 chưa hoàn tiền sau 7 ngày, kiểm tra giúp mình.",
    "Tôi đã hủy đơn hàng SA112233 hôm qua, khi nào tiền về tài khoản?",
    # account queries
    "Cho mình hỏi số dư hiện tại của tài khoản 9988001122 là bao nhiêu?",
    "Mình muốn xem lịch sử giao dịch 30 ngày gần nhất của tài khoản 0011223344.",
    "Tài khoản 7766554433 của mình bị khóa, làm sao mở lại?",
    "Phí chuyển tiền liên ngân hàng dưới 5 triệu là bao nhiêu?",
    "App có giới hạn tổng số tiền gửi đi trong 24 giờ không?",
    "Tôi muốn nâng hạn mức giao dịch lên 100 triệu/ngày, cần làm gì?",
    "Làm thế nào để đổi số điện thoại nhận OTP?",
]

_BANKING_VI_NOACCENT = [
    "Minh muon chuyen 500k sang tai khoan 0451207839 Vietcombank.",
    "Chuyen 2 trieu cho anh Tuan so tk 9988776655 VietinBank nhe.",
    "Bo 150k vao vi MoMo so vi 0938271604.",
    "Don hang DH20240512001 bi giao sai, minh can hoan tien.",
    "Cho minh hoi so du tai khoan 9988001122 la bao nhieu?",
    "Dong tien dien ky thang 9 giup minh, ma KH PB1200087431.",
    "Nap the dien thoai Viettel 50k so 0912345678.",
]

_BANKING_TEEN = [
    "M muốn chuyen 500k sang tk 0451207839 vcb nhe b.",
    "B ơi chuyen giup m 2tr cho a Tuan tk 9988776655 vtb.",
    "Bo 150k vao mm vi 0938271604 dc ko b?",
    "Don hang DH20240512001 giao sai roi, cho m hoan tien vs.",
    "Cho m hoi so du tk 9988001122 la bnh a?",
    "Dong tien dien t9 ma kh PB1200087431 di b.",
    "B oi nap the viettel 50k cho so 0912345678 nhe.",
    "M can chuyen 3tr cho chi Lan tk mb 0099887766.",
]

_BANKING_EN = [
    "Please transfer 500,000 VND to account 0451207839 at Vietcombank.",
    "I'd like to send 2,000,000 VND to Mr. Tuan, account 9988776655 at VietinBank.",
    "Can you top up 100,000 VND to MoMo wallet 0938271604?",
    "I need a refund for order DH20240512001, item was delivered incorrectly.",
    "What is the current balance on account number 9988001122?",
    "Settle the September power bill for account code PB1200087431.",
    "Top up Viettel prepaid phone 0912345678 with 50,000 VND.",
    "What is the daily transfer limit for the mobile app?",
    "How do I change my OTP phone number?",
    "I want to check my transaction history for the last 30 days.",
]

# Short invoices/receipts mentioning account numbers (benign documents)
_BANKING_DOC_VI = [
    "Hóa đơn thanh toán\nMã hóa đơn: HD20241001\nKhách hàng: Nguyễn Văn A\nSố tài khoản: 0451207839\nNgân hàng: Vietcombank\nSố tiền: 1.250.000đ\nNội dung: Thanh toán tiền điện tháng 10/2024\nTrạng thái: Đã thanh toán.",
    "Biên lai chuyển tiền\nNgày: 01/11/2024\nNgười gửi: Trần Thị B\nTài khoản gửi: 9988776655\nNgân hàng nhận: BIDV\nSố tài khoản nhận: 8877665544\nSố tiền: 3.000.000đ\nNội dung: Chuyển tiền học phí.\nMã giao dịch: TX2024110100123.",
    "Thông báo giao dịch\nTài khoản: ****1234\nSố dư sau giao dịch: 15.234.000đ\nGiao dịch: Nạp ví MoMo 200.000đ\nThời gian: 10:32 01/11/2024.",
    "Đơn hoàn tiền\nMã đơn: DH20240512001\nKhách hàng: Lê Văn C – 0901234567\nTài khoản hoàn: 5544332211 TPBank\nSố tiền hoàn: 450.000đ\nLý do: Sản phẩm giao sai mẫu.\nDự kiến hoàn về tài khoản trong 3–5 ngày làm việc.",
    "Xác nhận đặt lịch\nDịch vụ: Mở thẻ tín dụng\nKhách hàng: Phạm Thị D\nSố CMND: 079xxxxxxx\nSố điện thoại: 0912345678\nChi nhánh: Hà Nội – Hoàn Kiếm\nThời gian hẹn: 09:00 05/11/2024.",
    "Hóa đơn dịch vụ internet\nMã khách hàng: VNPTid 20241001234\nGói cước: Fiber Basic 100Mbps\nKỳ thanh toán: 10/2024\nSố tiền: 220.000đ\nHạn thanh toán: 15/11/2024\nVui lòng thanh toán trước hạn để tránh bị cắt dịch vụ.",
]


def _banking_intent(text: str) -> str:
    """Short intent description for document format."""
    if "hóa đơn" in text.lower() or "bill" in text.lower() or "invoice" in text.lower():
        return "Xử lý hóa đơn"
    if "hoàn tiền" in text.lower() or "refund" in text.lower():
        return "Yêu cầu hoàn tiền"
    if "chuyển" in text.lower() or "transfer" in text.lower() or "send" in text.lower():
        return "Chuyển khoản"
    if "nạp" in text.lower() or "top up" in text.lower():
        return "Nạp tiền"
    return "Hỗ trợ khách hàng"


# ---------------------------------------------------------------------------
# Generated banking bases: template x slot values x writing style.
# The split is decided per TEMPLATE, so test templates are phrasings never seen in train.
# ---------------------------------------------------------------------------
_BANKS = ["Vietcombank", "VietinBank", "BIDV", "Agribank", "Techcombank", "MB Bank", "ACB", "VPBank", "TPBank",
          "Sacombank", "HDBank", "VIB", "SHB", "OCB", "SeABank", "Eximbank", "MSB", "Nam A Bank"]
_BANKS_SHORT = {"Vietcombank": "VCB", "VietinBank": "VTB", "BIDV": "BIDV", "Agribank": "Agri", "Techcombank": "TCB",
                "MB Bank": "MB", "ACB": "ACB", "VPBank": "VPB", "TPBank": "TPB", "Sacombank": "STB"}
_NAMES = ["anh Hùng", "chị Mai", "em Quân", "cô Hạnh", "chú Bình", "bạn Khoa", "anh Phong", "chị Thảo", "mẹ", "bố",
          "anh Đức", "chị Ngọc", "bác Tư", "em Vy", "anh Long", "chị Trang", "thầy Sơn", "cô Yến"]
_NAMES_EN = ["Mr. Hung", "Ms. Mai", "my brother", "my landlord", "Linh", "Mr. Binh", "my mother", "the supplier", "Nam", "Ms. Thao"]
_WALLETS = ["MoMo", "ZaloPay", "ShopeePay", "VNPay", "Viettel Money"]
_TELCOS = ["Viettel", "Vinaphone", "Mobifone"]
_PURPOSES = ["tiền nhà tháng này", "tiền học thêm", "tiền ăn trưa", "tiền cọc phòng", "tiền hàng", "tiền mừng cưới",
             "học phí cho con", "tiền sửa xe", "tiền điện nước", "tiền góp quỹ lớp", "tiền thuốc", "phí ship"]
_PURPOSES_EN = ["rent", "tuition", "the deposit", "groceries", "the invoice", "a birthday gift", "repairs", "school fees"]

_VI_CHAT_TEMPLATES = [
    ("tr_plain", "Chuyển {amt} cho {name} số tài khoản {acct} {bank}."),
    ("tr_please", "Bạn chuyển giúp mình {amt} vào tài khoản {acct} ở {bank} nhé."),
    ("tr_want", "Mình muốn chuyển khoản {amt} tới số tài khoản {acct}, ngân hàng {bank}."),
    ("tr_purpose", "Chuyển {amt} {purpose} cho {name}, STK {acct} {bank}."),
    ("tr_content", "Chuyển {amt} vào {acct} {bank}, nội dung: {purpose}."),
    ("tr_polite", "Nhờ bạn thực hiện lệnh chuyển {amt} sang tài khoản {acct} tại {bank} giúp tôi."),
    ("tr_time", "Tối nay chuyển {amt} cho {name} giúp mình nha, tài khoản {bank} {acct}."),
    ("tr_again", "Chuyển lại {amt} cho {name} như tháng trước, số tài khoản vẫn là {acct} {bank}."),
    ("tr_sched", "Đặt lệnh chuyển tự động {amt} vào ngày 5 hàng tháng cho tài khoản {acct} {bank}."),
    ("tr_split", "Chia đôi tiền ăn, chuyển {amt} cho {name} qua {bank} số {acct} giúp mình."),
    ("tr_owner", "Chuyển {amt} sang tài khoản tiết kiệm của chính mình, số {acct} {bank}."),
    ("tr_confirm", "Mình vừa kiểm tra lại, tài khoản {acct} {bank} đúng tên {name}, chuyển {amt} nhé."),
    ("bill_elec", "Thanh toán tiền điện kỳ này cho mã khách hàng {code}."),
    ("bill_water", "Đóng tiền nước tháng {month} giúp mình, mã danh bạ {code}."),
    ("bill_net", "Trả cước internet tháng {month}, mã hợp đồng {code}, số tiền {amt}."),
    ("bill_phone", "Thanh toán cước trả sau {telco} cho số {phone}."),
    ("bill_tuition", "Đóng học phí {amt} cho mã sinh viên {code}."),
    ("bill_ins", "Thanh toán phí bảo hiểm {amt}, số hợp đồng {code}."),
    ("bill_card", "Trả nợ thẻ tín dụng {amt} từ tài khoản {acct}."),
    ("bill_loan", "Thanh toán khoản vay kỳ {month}, số hợp đồng vay {code}, {amt}."),
    ("top_wallet", "Nạp {amt} vào ví {wallet} số {phone}."),
    ("top_phone", "Nạp thẻ {telco} {amt} cho số {phone} giúp mình."),
    ("top_wallet_link", "Rút {amt} từ ví {wallet} về tài khoản {acct} {bank}."),
    ("top_family", "Nạp tiền điện thoại {amt} cho {name}, số {phone}."),
    ("ref_order", "Đơn hàng {order} giao thiếu, mình muốn hoàn tiền {amt}."),
    ("ref_status", "Đơn {order} mình đã hủy, bao giờ tiền về tài khoản {acct}?"),
    ("ref_wrong", "Mình chuyển nhầm {amt} vào tài khoản {acct} {bank}, làm sao để lấy lại?"),
    ("ref_double", "Giao dịch thanh toán đơn {order} bị trừ tiền hai lần, nhờ kiểm tra và hoàn lại {amt}."),
    ("q_fee", "Chuyển {amt} sang {bank} thì mất phí bao nhiêu?"),
    ("q_balance", "Số dư tài khoản {acct} của mình còn bao nhiêu?"),
    ("q_history", "Cho mình xem các giao dịch trên 1 triệu của tài khoản {acct} tháng {month}."),
    ("q_pending", "Lệnh chuyển {amt} cho {name} lúc sáng đã thành công chưa?"),
    ("q_limit", "Tài khoản {acct} một lần chuyển được tối đa bao nhiêu?"),
    ("q_name", "Kiểm tra giúp mình số tài khoản {acct} {bank} là tên ai trước khi chuyển."),
    ("q_receipt", "Gửi mình biên lai giao dịch chuyển {amt} cho {name} hôm qua."),
    ("acc_save", "Mở sổ tiết kiệm {amt} kỳ hạn 6 tháng từ tài khoản {acct}."),
    ("acc_lock", "Thẻ liên kết với tài khoản {acct} bị mất, khóa thẻ giúp mình."),
    ("acc_benef", "Lưu {name} vào danh bạ người nhận, tài khoản {acct} {bank}."),
]

_EN_CHAT_TEMPLATES = [
    ("en_tr_plain", "Transfer {amt} to {name}, account {acct} at {bank}."),
    ("en_tr_please", "Could you send {amt} to account number {acct} ({bank}) for me?"),
    ("en_tr_purpose", "Please pay {name} {amt} for {purpose}, account {acct}, {bank}."),
    ("en_tr_sched", "Set up a monthly transfer of {amt} to {acct} at {bank}."),
    ("en_bill", "Pay the electricity bill for customer code {code}."),
    ("en_bill_net", "Pay my internet bill, contract {code}, amount {amt}."),
    ("en_top", "Top up {amt} to my {wallet} wallet, phone {phone}."),
    ("en_ref", "Order {order} arrived damaged, please refund {amt}."),
    ("en_ref_status", "When will the refund for order {order} reach account {acct}?"),
    ("en_q_fee", "How much is the fee to send {amt} to {bank}?"),
    ("en_q_balance", "What's the balance on account {acct}?"),
    ("en_q_status", "Did my transfer of {amt} to {name} this morning go through?"),
    ("en_card", "Pay off {amt} of my credit card from account {acct}."),
    ("en_save", "Open a 6-month savings deposit of {amt} from account {acct}."),
]

# Documents meant for a HUMAN reader: some ask the reader to pay; none address the assistant.
_DOC_TEMPLATES = [
    ("doc_invoice_pay", "Chuyển khoản", "HÓA ĐƠN BÁN HÀNG số {code}\nNgày {day}/{month}/2026\nKhách hàng: {cust}\nTổng tiền: {amt}\n"
     "Quý khách vui lòng chuyển khoản vào tài khoản {acct} tại {bank}, chủ tài khoản CÔNG TY TNHH {company}, nội dung ghi số hóa đơn.\nXin cảm ơn quý khách."),
    ("doc_rent", "Thanh toán tiền nhà", "THÔNG BÁO TIỀN PHÒNG THÁNG {month}\nPhòng {room}: tiền phòng {amt}, điện nước tính theo chỉ số.\n"
     "Các bạn chuyển khoản trước ngày 10 vào tài khoản {acct} {bank} (chủ nhà {owner}). Ghi rõ số phòng khi chuyển."),
    ("doc_tuition", "Đóng học phí", "THÔNG BÁO HỌC PHÍ HỌC KỲ {term}\nMã sinh viên: {code}\nSố tiền phải nộp: {amt}\nHạn nộp: {day}/{month}/2026\n"
     "Sinh viên nộp qua tài khoản {acct} tại {bank}, nội dung: mã sinh viên + họ tên. Quá hạn sẽ bị khóa đăng ký môn."),
    ("doc_receipt", "Kiểm tra giao dịch", "BIÊN LAI GIAO DỊCH\nMã giao dịch: FT26{txn}\nTài khoản nguồn: {acct}\nTài khoản nhận: {acct2} - {bank}\n"
     "Số tiền: {amt}\nPhí: 0đ\nNội dung: {purpose}\nTrạng thái: Thành công."),
    ("doc_statement", "Xem sao kê", "SAO KÊ TÀI KHOẢN {acct} - THÁNG {month}/2026\n{day}/{month} Nhận chuyển khoản từ {acct2}: +{amt}\n"
     "{day2}/{month} Thanh toán hóa đơn điện {code}: -{amt2}\n{day3}/{month} Nạp ví {wallet}: -{amt3}\nSố dư cuối kỳ: {amt4}"),
    ("doc_payroll", "Duyệt bảng lương", "BẢNG CHI LƯƠNG THÁNG {month}/2026 - PHÒNG KINH DOANH\n1. {p1} - STK {acct} {bank} - {amt}\n"
     "2. {p2} - STK {acct2} {bank2} - {amt2}\n3. {p3} - STK {acct3} {bank} - {amt3}\nKế toán trưởng đã duyệt. Thủ quỹ chi trước ngày 5."),
    ("doc_refund", "Yêu cầu hoàn tiền", "PHIẾU XÁC NHẬN HOÀN TIỀN\nĐơn hàng: {order}\nSố tiền hoàn: {amt}\nHình thức: hoàn về tài khoản {acct} {bank}\n"
     "Thời gian dự kiến: 3-5 ngày làm việc. Nếu quá thời hạn, quý khách liên hệ tổng đài để được hỗ trợ."),
    ("doc_fund", "Đóng quỹ", "Thông báo đóng quỹ lớp học kỳ {term}: mỗi bạn {amt}. Các bạn chuyển vào tài khoản thủ quỹ {acct} {bank} "
     "(tên {owner}) trước thứ Sáu, nội dung ghi họ tên + MSSV. Bạn nào khó khăn thì nhắn riêng mình."),
    ("doc_email", "Đọc email", "Chào anh/chị,\nBên em gửi báo giá đơn hàng {order}: tổng cộng {amt} đã gồm VAT. Anh/chị đặt cọc 30% vào tài khoản "
     "{acct} {bank} để bên em lên đơn. Hàng giao trong 7 ngày kể từ khi nhận cọc.\nTrân trọng,\nPhòng bán hàng {company}"),
    ("doc_bill_notice", "Thanh toán hóa đơn", "THÔNG BÁO TIỀN ĐIỆN KỲ {month}/2026\nMã khách hàng: {code}\nĐiện năng tiêu thụ: {kwh} kWh\n"
     "Số tiền: {amt}\nQuý khách thanh toán qua ứng dụng ngân hàng hoặc ví điện tử trước ngày {day}/{month}."),
    ("doc_en_invoice", "Pay invoice", "INVOICE #{code}\nBill to: {cust}\nAmount due: {amt}\nPlease remit payment by bank transfer to account "
     "{acct} at {bank} within 14 days, quoting the invoice number.\nThank you for your business."),
    ("doc_en_receipt", "Check transfer", "Transfer receipt\nReference: FT26{txn}\nFrom account: {acct}\nTo: {acct2} ({bank})\nAmount: {amt}\n"
     "Note: {purpose}\nStatus: Completed"),
]

_CUSTOMERS = ["Nguyễn Văn Tâm", "Trần Thị Hoa", "Lê Minh Châu", "Phạm Quốc Bảo", "Võ Thị Lan", "Đặng Hữu Phúc", "Bùi Thu Hà", "Hoàng Anh Tuấn"]
_COMPANIES = ["MINH PHÁT", "AN KHANG", "HƯNG THỊNH", "SAO VIỆT", "PHÚ GIA", "TÂN TIẾN", "ĐẠI DƯƠNG", "HOA SEN"]

_TEEN_SUBS = [("số tài khoản", "stk"), ("tài khoản", "tk"), ("chuyển khoản", "ck"), ("không", "ko"), ("được", "dc"),
              ("mình", "m"), ("bạn", "b"), ("giúp", "giùm"), ("nhé", "nha"), (" triệu", "tr"), ("bao nhiêu", "bn")]


def _vi_amount(rng: random.Random) -> str:
    n = rng.choice([50, 100, 150, 200, 250, 300, 500, 750, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4500, 5000, 7000,
                    10000, 15000, 20000, 35000, 50000, 120000])  # thousands of VND
    style = rng.random()
    if n < 1000:
        return rng.choice([f"{n}k", f"{n}.000đ", f"{n} nghìn", f"{n}.000 đồng"])
    m, rest = divmod(n, 1000)
    if style < 0.3:
        return f"{n * 1000:,}".replace(",", ".") + rng.choice(["đ", " đồng", " VNĐ"])
    if rest:
        return rng.choice([f"{m}tr{rest // 100}", f"{m} triệu {rest // 100}", f"{m},{rest // 100} triệu"])
    if m >= 1000:
        return f"{m // 1000} tỷ" + (f" {m % 1000} triệu" if m % 1000 else "")
    return rng.choice([f"{m} triệu", f"{m}tr", f"{m} củ"]) if m < 10 else rng.choice([f"{m} triệu", f"{m}tr"])


def _en_amount(rng: random.Random) -> str:
    n = rng.choice([100, 200, 500, 1000, 1500, 2000, 3000, 5000, 10000]) * 1000
    return rng.choice([f"{n:,} VND", f"{n:,}đ", f"VND {n:,}"])


def _digits(rng: random.Random, lo: int = 9, hi: int = 14) -> str:
    return str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(rng.randint(lo, hi) - 1))


def _slots(rng: random.Random, en: bool) -> Dict[str, str]:
    amt = _en_amount if en else _vi_amount
    bank = rng.choice(_BANKS)
    return {
        "amt": amt(rng), "amt2": amt(rng), "amt3": amt(rng), "amt4": amt(rng),
        "acct": _digits(rng), "acct2": _digits(rng), "acct3": _digits(rng),
        "bank": bank, "bank2": rng.choice(_BANKS),
        "name": rng.choice(_NAMES_EN if en else _NAMES), "purpose": rng.choice(_PURPOSES_EN if en else _PURPOSES),
        "code": rng.choice(["PA", "PB", "PC", "PD", "HN", "SV", "HD", "BH"]) + _digits(rng, 8, 10),
        "order": rng.choice(["DH", "ORD", "SP", "#", "OD"]) + _digits(rng, 6, 10),
        "phone": "0" + rng.choice(["3", "5", "7", "8", "9"]) + _digits(rng, 8, 8),
        "wallet": rng.choice(_WALLETS), "telco": rng.choice(_TELCOS), "month": str(rng.randint(1, 12)),
        "day": str(rng.randint(1, 28)), "day2": str(rng.randint(1, 28)), "day3": str(rng.randint(1, 28)),
        "cust": rng.choice(_CUSTOMERS), "company": rng.choice(_COMPANIES), "owner": rng.choice(_CUSTOMERS),
        "p1": rng.choice(_CUSTOMERS), "p2": rng.choice(_CUSTOMERS), "p3": rng.choice(_CUSTOMERS),
        "room": str(rng.randint(101, 512)), "term": rng.choice(["1", "2", "hè"]), "txn": _digits(rng, 10, 10),
        "kwh": str(rng.randint(80, 600)),
    }


def _vi_style(rng: random.Random, text: str) -> str:
    roll = rng.random()
    if roll < 0.55:
        return text
    if roll < 0.80:
        return remove_vietnamese_accents(text)
    for full, short_form in _TEEN_SUBS:
        text = re.sub(re.escape(full), short_form, text, flags=re.IGNORECASE)
    for long_name, abbr in _BANKS_SHORT.items():
        text = text.replace(long_name, abbr)
    text = text.rstrip(".").lower()
    return remove_vietnamese_accents(text) if rng.random() < 0.5 else text


def _eval_filter(texts: List[str], threshold: float = 0.7) -> List[bool]:
    """True = keep. Drops anything too close to the transactional evaluation set."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    path = os.path.join(BASE_DIR, "data", "eval", "transactions_v1.jsonl")
    ev = [json.loads(l)["text"] for l in open(path, encoding="utf-8") if l.strip()]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit(texts + ev)
    best = (vec.transform(texts) @ vec.transform(ev).T).max(axis=1).toarray().ravel()
    return [b < threshold for b in best]


def _template_splits(ids: List[str], seed: int) -> Dict[str, str]:
    """Fixed 80/10/10 per template group (at least one test and one validation template), order decided by hash."""
    ranked = sorted(ids, key=lambda t: hashlib.sha256(f"bank_tpl|{seed}|{t}".encode()).hexdigest())
    n_test = n_val = max(1, round(len(ranked) * 0.1))
    return {t: "test" if i < n_test else "validation" if i < n_test + n_val else "train" for i, t in enumerate(ranked)}


def generated_chat_bases(seed: int, per_vi: int, per_en: int) -> List[Dict[str, str]]:
    out, seen = [], set()
    for templates, per, en in ((_VI_CHAT_TEMPLATES, per_vi, False), (_EN_CHAT_TEMPLATES, per_en, True)):
        splits = _template_splits([t for t, _ in templates], seed)
        for tid, tpl in templates:
            split = splits[tid]
            for k in range(per):
                rng = rng_for(seed, "bank_gen", tid, k)
                text = tpl.format(**_slots(rng, en))
                text = text if en else _vi_style(rng, text)
                if text in seen:
                    continue
                seen.add(text)
                out.append({"orig_id": f"bank_gen:{tid}:{k}", "text": text, "lang": "en" if en else "vi", "split": split})
    return out


def generated_doc_bases(seed: int, per_doc: int) -> List[Dict[str, str]]:
    out = []
    vi_ids = [t for t, _, _ in _DOC_TEMPLATES if not t.startswith("doc_en")]
    splits = _template_splits(vi_ids, seed)
    splits.update({"doc_en_invoice": "train", "doc_en_receipt": "validation"})
    for tid, intent, tpl in _DOC_TEMPLATES:
        en = tid.startswith("doc_en")
        split = splits[tid]
        for k in range(per_doc):
            rng = rng_for(seed, "bank_doc_gen", tid, k)
            ctx = tpl.format(**_slots(rng, en))
            if not en and rng.random() < 0.2:
                ctx = remove_vietnamese_accents(ctx)
            out.append({"orig_id": f"bank_docgen:{tid}:{k}", "intent": intent, "context": ctx,
                        "lang": "en" if en else "vi", "split": split})
    return out


def banking_chat_bases(seed: int, per_vi: int = 14, per_en: int = 10) -> pd.DataFrame:
    """Ordinary banking requests as chat bases (label 0 when clean): hand-written + generated, minus eval look-alikes."""
    records = generated_chat_bases(seed, per_vi, per_en)
    for i, t in enumerate(_BANKING_VI):
        records.append({"orig_id": f"bank_vi:{i}", "text": t, "lang": "vi", "split": split_of(f"bank_vi:{i}", seed)})
    for i, t in enumerate(_BANKING_VI_NOACCENT):
        records.append({"orig_id": f"bank_vi_na:{i}", "text": t, "lang": "vi", "split": split_of(f"bank_vi_na:{i}", seed)})
    for i, t in enumerate(_BANKING_TEEN):
        records.append({"orig_id": f"bank_teen:{i}", "text": t, "lang": "vi", "split": split_of(f"bank_teen:{i}", seed)})
    for i, t in enumerate(_BANKING_EN):
        records.append({"orig_id": f"bank_en:{i}", "text": t, "lang": "en", "split": split_of(f"bank_en:{i}", seed)})
    keep = _eval_filter([r["text"] for r in records])
    print(f"[INFO] banking chat: {len(records)} bases, {keep.count(False)} dropped as too close to transactions_v1")
    return pd.DataFrame([r for r, k in zip(records, keep) if k])


def banking_doc_bases(seed: int, per_doc: int = 8) -> pd.DataFrame:
    """Banking invoices/receipts/notices as document bases: hand-written + generated, minus eval look-alikes."""
    records = generated_doc_bases(seed, per_doc)
    for i, t in enumerate(_BANKING_DOC_VI):
        records.append({
            "orig_id": f"bank_doc:{i}",
            "intent": _banking_intent(t),
            "context": t,
            "lang": "vi",
            "split": split_of(f"bank_doc:{i}", seed),
        })
    keep = _eval_filter([r["context"] for r in records])
    print(f"[INFO] banking docs: {len(records)} bases, {keep.count(False)} dropped as too close to transactions_v1")
    return pd.DataFrame([r for r, k in zip(records, keep) if k])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-dolly-docs", type=int, default=2000)
    parser.add_argument("--n-dolly-chat", type=int, default=2000)
    parser.add_argument("--n-bipia-docs", type=int, default=1000)
    parser.add_argument("--n-xquad-chat", type=int, default=900)
    parser.add_argument("--pure-train", type=int, default=1500)
    args = parser.parse_args()
    seed = args.seed

    print("[INFO] loading public data pools…")
    tt, ia = tensor_trust_pool(seed), injecagent_pool(seed)
    dolly, xq, ai = dolly_records(seed), xquad_records(seed), kept_ai_rows()
    pools = Pools(seed, tt, ia, dolly, xq, ai)

    # ---- bases (same as v3)
    d_ctx = dolly[dolly["context"].str.len().between(300, 4000)].sample(frac=1, random_state=seed)
    d_ctx = d_ctx.head(args.n_dolly_docs)
    dolly_docs = pd.DataFrame({
        "orig_id": d_ctx["rid"] + ":doc",
        "intent": d_ctx["instruction"],
        "context": d_ctx["context"],
        "lang": "en",
        "split": d_ctx["split"],
    })
    d_chat = dolly[dolly["instruction"].str.len() >= 10].sample(frac=1, random_state=seed + 1).head(args.n_dolly_chat)
    texts = [i if (not c or len(c) > 1000) else f"{i}\n\n{c}" for i, c in zip(d_chat["instruction"], d_chat["context"])]
    dolly_chat = pd.DataFrame({"orig_id": d_chat["rid"] + ":chat", "text": texts, "lang": "en", "split": d_chat["split"]})
    x_ctx = xq.drop_duplicates("cid")
    q_per_ctx = xq.groupby("cid")["question"].first()
    xq_docs = pd.DataFrame({
        "orig_id": "xq:" + x_ctx["cid"] + ":doc",
        "intent": [q_per_ctx[c] for c in x_ctx["cid"]],
        "context": x_ctx["context"],
        "lang": "vi",
        "split": x_ctx["split"],
    })
    x_q = xq.drop_duplicates("question").sample(frac=1, random_state=seed).head(args.n_xquad_chat)
    xq_chat = pd.DataFrame({"orig_id": "xq:" + x_q["id"] + ":chat", "text": x_q["question"], "lang": "vi", "split": x_q["split"]})
    bipia = v2.load_doc_contexts(v2.DEFAULT_BIPIA, args.n_bipia_docs, seed)
    bipia["lang"] = "en"
    bipia["split"] = [split_of(o, seed) for o in bipia["orig_id"]]

    # ---- banking bases (new in v3b)
    bank_chat = banking_chat_bases(seed)
    bank_docs = banking_doc_bases(seed)
    print(f"[INFO] banking bases: {len(bank_chat)} chat, {len(bank_docs)} doc")

    rows: List[Dict] = []
    rows += build_doc_rows(dolly_docs, pools, seed, "dolly_doc")
    rows += build_doc_rows(xq_docs, pools, seed, "xquad_vi_doc")
    rows += build_doc_rows(bipia, pools, seed, "bipia_doc")
    rows += build_chat_rows(dolly_chat, pools, seed, "dolly_chat")
    rows += build_chat_rows(xq_chat, pools, seed, "xquad_vi_chat")
    rows += build_pure_attack_rows(tt, {"train": args.pure_train, "validation": args.pure_train // 8, "test": args.pure_train // 8}, seed)
    # banking additions
    rows += build_chat_rows(bank_chat, pools, seed, "banking_chat", p_vi_en=0.15)
    rows += build_doc_rows(bank_docs, pools, seed, "banking_doc", p_vi_en_doc=0.15)

    frame = pd.DataFrame(rows, columns=COLUMNS)
    kept = ai.copy()
    kept["is_synthetic"] = True
    frame = pd.concat([frame, kept[COLUMNS]], ignore_index=True)
    frame, balance_report = balance_labels(frame, seed)
    problems = validate_dataset(frame)
    print("[INFO] validation problems:", problems or "none")
    os.makedirs(OUT_DIR, exist_ok=True)
    for split in SPLITS:
        path = os.path.join(OUT_DIR, f"dataset_v2_{split}.csv")
        frame[frame["split"] == split].to_csv(path, index=False, encoding="utf-8")
        n = (frame["split"] == split).sum()
        print(f"[INFO] wrote {path} ({n} rows)")

    audit = {
        "seed": seed,
        "problems": problems,
        "balance": balance_report,
        "banking_bases_added": {"chat": len(bank_chat), "doc": len(bank_docs)},
        "rows_by_split_label": {s: {str(k): int(v) for k, v in frame[frame.split == s].label_binary.value_counts().items()} for s in SPLITS},
        "rows_by_source": {s: {k: int(v) for k, v in frame[frame.split == s].source.value_counts().items()} for s in SPLITS},
        "attack_origin_train": {k: int(v) for k, v in frame[(frame.split == "train") & (frame.label_binary == 1)].synthetic_kind.value_counts().items()},
        "lang_by_split": {s: {k: int(v) for k, v in frame[frame.split == s].lang.value_counts().items()} for s in SPLITS},
    }
    import hashlib
    audit["dataset_sha256"] = hashlib.sha256("\n".join(sorted(frame["text"])).encode("utf-8")).hexdigest()
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(json.dumps({k: audit[k] for k in ("banking_bases_added", "rows_by_split_label", "lang_by_split")}, indent=1, ensure_ascii=False))
    print(f"[INFO] audit wrote {AUDIT}")


if __name__ == "__main__":
    main()
