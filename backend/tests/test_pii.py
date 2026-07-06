import pytest
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
