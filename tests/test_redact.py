from cuas.safety.redact import redact_dict, redact_text


def test_redacts_ssn_and_account_numbers():
    text = "ssn 123-45-6789 account SV-001122 token=abcd"
    out = redact_text(text)
    assert "123-45-6789" not in out
    assert "SV-001122" not in out
    assert "abcd" not in out
    assert "[SSN]" in out
    assert "[ACCOUNT]" in out


def test_redact_dict_by_key():
    payload = {"password": "teller", "member_id": "12345", "nested": {"token": "xyz"}}
    out = redact_dict(payload)
    assert out["password"] == "[REDACTED]"
    assert out["nested"]["token"] == "[REDACTED]"
    assert out["member_id"] == "12345"
