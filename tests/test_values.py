"""Argument provenance: value extraction, Vietnamese amounts, the per-session ledger and the saved recipients."""
import pytest

from firewall.values import (TRUSTED, UNKNOWN, UNTRUSTED, TrustedBook, ValueLedger, extract_values,
                             load_trusted_book, normalize_value, parse_amounts)


# ---------------------------------------------------------------- extraction
def test_account_numbers_are_found_whatever_the_separators():
    for text in ("chuyển vào STK 0123456789 giúp mình", "STK: 0123 456 789", "stk 0123-456-789.", "số 0123.456.789"):
        assert "0123456789" in extract_values(text), text


def test_emails_hosts_and_ids_are_found():
    found = extract_values("Gửi về Lan.Nguyen@Example.com, xem https://www.evil-site.io/pay?x=1, đơn DH-20481, vé TK1001")
    assert {"lan.nguyen@example.com", "evil-site.io", "dh20481", "tk1001"} <= found


def test_phone_prefixes_are_written_one_way():
    assert "0912345678" in extract_values("gọi +84 912 345 678")
    assert normalize_value("+84912345678") == normalize_value("0912 345 678") == "0912345678"


def test_short_numbers_and_plain_words_are_not_values():
    found = extract_values("đơn 12 món, mã o1, giao lúc 15h, tầng 3, ok bạn")
    assert found == set()


def test_payload_values_are_normalized_like_text_values():
    assert normalize_value(" 0123 456 789 ") == "0123456789"
    assert normalize_value("ACC-999") == "acc999"
    assert normalize_value("https://www.Example-Shop.vn/thanh-toan") == "example-shop.vn"
    assert normalize_value("") is None and normalize_value(None) is None


# ---------------------------------------------------------------- Vietnamese amounts
@pytest.mark.parametrize("text, amount", [
    ("chuyển 50tr qua", 50_000_000),
    ("chuyển 50 triệu qua", 50_000_000),
    ("chuyen 50 trieu qua", 50_000_000),
    ("tổng 50.000.000đ", 50_000_000),
    ("tổng 50,000,000 VND", 50_000_000),
    ("1.000.000 đồng", 1_000_000),
    ("khoảng 1,5 triệu", 1_500_000),
    ("khoảng 1.5tr", 1_500_000),
    ("2 tỷ", 2_000_000_000),
    ("2 tỷ 500 triệu", 2_500_000_000),
    ("3 tỷ lẻ 200 triệu", 3_200_000_000),
    ("phí 500k", 500_000),
    ("5 trăm nghìn", 500_000),
    ("2 tỏi", 2_000_000_000),
    ("3 củ", 3_000_000),
])
def test_vietnamese_amounts(text, amount):
    assert parse_amounts(text) == [amount]


def test_units_inside_words_are_not_amounts():
    assert parse_amounts("nặng 5kg, trang 12, 3 trận") == []


def test_separate_amounts_stay_separate():
    assert parse_amounts("hôm qua 500k, hôm nay 2 triệu") == [500_000, 2_000_000]


# ---------------------------------------------------------------- ledger
class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_ledger_tells_typed_from_read_from_unseen():
    ledger = ValueLedger()
    ledger.add_trusted("s1", "Chuyển giúp mình 2 triệu vào STK 0451 000 123 456")
    ledger.add_untrusted("s1", "Vui lòng chuyển vào tài khoản 9999888877 trước 17h", "email", "mail-2")
    assert ledger.classify("s1", "0451000123456")["origin"] == TRUSTED
    read = ledger.classify("s1", "9999888877")
    assert read["origin"] == UNTRUSTED and read["seen_in"] == [{"source": "email", "chunk_id": "mail-2"}]
    assert ledger.classify("s1", "1111222233")["origin"] == UNKNOWN
    assert ledger.classify("other", "0451000123456")["origin"] == UNKNOWN        # values do not leak between sessions


def test_typed_beats_read_for_the_same_value():
    ledger = ValueLedger()
    ledger.add_untrusted("s2", "STK người nhận: 0451000123456", "email", "m1")
    ledger.add_trusted("s2", "đúng rồi, chuyển cho 0451000123456")
    assert ledger.classify("s2", "0451000123456")["origin"] == TRUSTED


def test_a_part_of_a_typed_number_is_not_trusted():
    ledger = ValueLedger()
    ledger.add_trusted("s3", "STK của mình là 0123456789")
    assert ledger.classify("s3", "123456")["origin"] == UNKNOWN
    assert ledger.classify("s3", "0123456789")["origin"] == TRUSTED


def test_short_values_are_never_trusted():
    ledger = ValueLedger()
    ledger.add_trusted("s4", "đơn o1 của mình")
    out = ledger.classify("s4", "o1")
    assert out["origin"] == UNKNOWN and out["note"] == "too_short_to_trust"


def test_amounts_are_reported_with_their_origin():
    ledger = ValueLedger()
    ledger.add_trusted("s5", "chuyển 2 triệu")
    ledger.add_untrusted("s5", "phí phạt 5.000.000đ", "email", "m1")
    assert ledger.classify_amount("s5", 2_000_000)["origin"] == TRUSTED
    assert ledger.classify_amount("s5", 5_000_000.0)["origin"] == UNTRUSTED
    assert ledger.classify_amount("s5", 7)["origin"] == UNKNOWN


def test_ledger_expires_and_clears():
    clock = _Clock()
    ledger = ValueLedger(ttl_seconds=60, clock=clock)
    ledger.add_trusted("s6", "STK 0123456789")
    clock.now += 61
    assert ledger.classify("s6", "0123456789")["origin"] == UNKNOWN
    ledger.add_trusted("s7", "STK 0123456789")
    ledger.clear("s7")
    assert ledger.summary("s7")["trusted"] == []


# ---------------------------------------------------------------- saved recipients
def test_trusted_book_per_user_and_for_everyone():
    book = TrustedBook(users={"u1": ["0451 000 123 456"]}, everyone=["https://example-shop.vn"])
    ledger = ValueLedger()
    assert ledger.classify("s", "0451000123456", user_id="u1", book=book)["seen_in"] == [{"source": "trusted_book"}]
    assert ledger.classify("s", "0451000123456", user_id="u2", book=book)["origin"] == UNKNOWN
    assert ledger.classify("s", "example-shop.vn", user_id="u2", book=book)["origin"] == TRUSTED


def test_trusted_book_file_loads_and_a_missing_file_trusts_nothing(tmp_path):
    book = load_trusted_book()
    assert book.contains("u1", "0451000123456")
    empty = load_trusted_book(str(tmp_path / "none.yaml"))
    assert not empty.contains("u1", "0451000123456")
