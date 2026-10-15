"""OTP setup codes. Secrets and accounts are invented."""

from __future__ import annotations

import base64
import urllib.parse

import pytest

from code_tools.codes.classify import classify

URI = b"otpauth://totp/Example%20Corp:erika@example.org?secret=JBSWY3DPEHPK3PXP&issuer=Example%20Corp"


def test_totp():
    p = classify(URI, "]Q1")
    assert p["type"] == "otpauth" and p["valid"] and p["warnings"] == [], p["errors"]
    assert (p["otp_type"], p["issuer"], p["account"], p["secret"]) == ("totp", "Example Corp", "erika@example.org",
                                                                       "JBSWY3DPEHPK3PXP")
    assert (p["algorithm"], p["digits"], p["period"]) == ("SHA1", 6, 30)
    assert "secret" in p["note"]


def test_hotp_and_parameters():
    p = classify(b"otpauth://hotp/erika?secret=JBSWY3DPEHPK3PXP&counter=7&digits=8&algorithm=sha256")
    assert p["valid"] and (p["counter"], p["digits"], p["algorithm"]) == (7, 8, "SHA256") and "period" not in p
    assert "issuer" not in p


def test_problems():
    p = classify(b"otpauth://hotp/erika?secret=JBSWY3DPEHPK3PXP")
    assert not p["valid"] and "counter" in p["errors"][0]
    p = classify(b"otpauth://totp/erika?secret=not-base32!")
    assert not p["valid"] and "base32" in p["errors"][0]
    p = classify(b"otpauth://totp/erika")
    assert not p["valid"] and "secret missing" in p["errors"]
    p = classify(b"otpauth://motp/erika?secret=JBSWY3DPEHPK3PXP")
    assert not p["valid"] and "unknown OTP type" in p["errors"][0]
    p = classify(URI.replace(b"issuer=Example%20Corp", b"issuer=Other"))
    assert p["valid"] and "differs" in p["warnings"][0]


def varint(n: int) -> bytes:
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    return varint(number << 3 | 2) + varint(len(value)) + value


def test_migration_export():
    secret = b"Hello!\xde\xad\xbe\xef"
    account = (field(1, secret) + field(2, b"erika@example.org") + field(3, b"Example Corp") + field(4, 1)
               + field(5, 1) + field(6, 2))
    hotp = field(1, b"\x01" * 10) + field(2, b"bob") + field(6, 1) + field(7, 42)
    payload = field(1, account) + field(1, hotp) + field(2, 1) + field(3, 1) + field(4, 0) + field(5, 123456)
    data = urllib.parse.quote(base64.b64encode(payload).decode())
    p = classify(f"otpauth-migration://offline?data={data}".encode(), "]Q1")
    assert p["type"] == "otpauth" and p["valid"], p["errors"]
    assert p["accounts"][0] == {"secret": base64.b32encode(secret).decode().rstrip("="),
                                "account": "erika@example.org", "issuer": "Example Corp", "otp_type": "totp",
                                "algorithm": "SHA1", "digits": 6}
    assert p["accounts"][1]["otp_type"] == "hotp" and p["accounts"][1]["counter"] == 42
    assert (p["version"], p["batch_size"], p["batch_id"]) == (1, 1, 123456)


def test_migration_problems():
    p = classify(b"otpauth-migration://offline?data=%%%")
    assert p["type"] == "otpauth" and not p["valid"]
    p = classify(b"otpauth-migration://offline?data=" + base64.b64encode(b"\x0a\x50\x01"))  # truncated field
    assert not p["valid"] and "cannot be decoded" in p["errors"][0]
    p = classify(b"otpauth-migration://offline")
    assert not p["valid"] and "data parameter missing" in p["errors"]


@pytest.mark.parametrize("payload", [b"otpauth:/totp", b"https://example.org/otpauth://totp/x", b"otp://totp/x"])
def test_not_otpauth(payload):
    assert classify(payload, "]Q1")["type"] != "otpauth"
