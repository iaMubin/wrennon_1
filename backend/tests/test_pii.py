from app.services.llm import mask_pii

def test_mask_emails():
    text = "My email is test.user@example.com, please contact me."
    masked = mask_pii(text)
    assert "test.user@example.com" not in masked
    assert "[EMAIL HIDDEN]" in masked

def test_mask_credit_cards():
    text = "Here is my card: 1234-5678-9012-3456 and another 123456789012345"
    masked = mask_pii(text)
    assert "1234-5678-9012-3456" not in masked
    assert "123456789012345" not in masked
    assert "[CARD HIDDEN]" in masked
    assert masked.count("[CARD HIDDEN]") == 2

def test_mask_phone_numbers():
    text = "Call me at +1-800-555-0199 or (123) 456-7890"
    masked = mask_pii(text)
    assert "800-555-0199" not in masked
    assert "(123) 456-7890" not in masked
    assert "[PHONE HIDDEN]" in masked

def test_mask_ssn():
    text = "My SSN is 123-45-6789 and also 987654321."
    masked = mask_pii(text)
    assert "123-45-6789" not in masked
    # 987654321 gets caught as SSN or possibly other things, but let's test the formatted one.
    assert "[SSN HIDDEN]" in masked

def test_mask_ip():
    text = "My server IP is 192.168.1.100."
    masked = mask_pii(text)
    assert "192.168.1.100" not in masked
    assert "[IP HIDDEN]" in masked

def test_mask_passwords():
    text = "My Password is secretPassword123!"
    masked = mask_pii(text)
    assert "secretPassword123!" not in masked
    assert "[PASSWORD HIDDEN]" in masked

def test_mask_address():
    text = "I live at 123 Main St, New York, NY 10001"
    masked = mask_pii(text)
    assert "123 Main St" not in masked
    assert "[ADDRESS HIDDEN]" in masked

def test_mask_names():
    text = "Hi, my name is John Doe and shipping to Alice"
    masked = mask_pii(text)
    assert "John Doe" not in masked
    assert "Alice" not in masked
    assert "[NAME HIDDEN]" in masked

def test_mask_empty_and_malformed():
    assert mask_pii("") == ""
    assert mask_pii("   ") == "   "
    assert mask_pii("None of your business") == "None of your business"


def test_benign_phrases_are_not_masked_as_names():
    # Regression: a global (?i) flag made [A-Z][a-z]+ match any word, so
    # "i'm checking" became "i'm [NAME HIDDEN]" and the bot hallucinated that
    # the customer had given their name.
    from app.services.llm import mask_pii
    for text in ["ok i'm checking", "I am looking for a jacket", "this is annoying"]:
        assert mask_pii(text) == text


def test_order_numbers_are_not_masked_as_ssn():
    from app.services.llm import mask_pii
    assert mask_pii("my order 123456789 is late") == "my order 123456789 is late"
    assert "[SSN HIDDEN]" in mask_pii("ssn 123-45-6789")
    assert "[NAME HIDDEN]" in mask_pii("My name is John Smith")


def test_money_moving_tools_not_reachable_by_llm():
    from app.services.tools import TOOL_EXECUTORS
    assert "process_refund" not in TOOL_EXECUTORS
    assert "update_subscription" not in TOOL_EXECUTORS


# --- Bangladeshi formats / secrets (regression for the PII-leak audit) -------

import pytest
from app.security.pii import mask_pii as _mask, redact_for_log, redact_secrets


@pytest.mark.parametrize("raw", [
    "01712345678", "01912-345678", "+8801712345678", "+880 1712-345678", "880-1712-345678",
])
def test_bd_phone_numbers_masked_with_correct_label(raw):
    out = _mask(f"call me on {raw} please")
    assert "[PHONE HIDDEN]" in out
    assert "[CARD HIDDEN]" not in out
    assert "345678" not in out


def test_bd_addresses_masked_english_and_bengali():
    assert "Dhanmondi" not in _mask("House 12, Road 5, Block C, Dhanmondi, Dhaka")
    assert "ধানমন্ডি" not in _mask("আমার ঠিকানা: বাসা ১২, রোড ৫, ধানমন্ডি, ঢাকা")
    assert "Mirpur" not in _mask("my address is flat 4B, Mirpur 10, Dhaka")


def test_lowercase_and_bengali_names_masked_with_explicit_trigger():
    assert "rahim" not in _mask("my name is rahim uddin and I need help")
    assert "রহিম" not in _mask("আমার নাম রহিম উদ্দিন")
    assert "karim" not in _mask("ship to Karim Hossain")


def test_passport_and_nid_masked():
    assert "A01234567" not in _mask("my passport is A01234567")
    assert "1990123456789" not in _mask("NID: 1990123456789")


def test_order_numbers_and_tracking_not_overmasked():
    assert _mask("order #1002 shipped") == "order #1002 shipped"
    assert _mask("track 1Z999AA10123456784") == "track 1Z999AA10123456784"


def test_secrets_redacted_from_logs():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abcdefghijklmnop"
    line = f"GET /ws/customer/abc?token={jwt} Authorization: Bearer {jwt} wk_live_abcdefgh12345678"
    out = redact_secrets(line)
    assert jwt not in out and "wk_live_abcdefgh" not in out
    assert "10.0.0.1" in redact_for_log("client 10.0.0.1 failed")   # IPs kept for ops
