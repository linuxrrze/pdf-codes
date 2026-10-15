"""One-time password setup codes: ``otpauth://`` and Google Authenticator's ``otpauth-migration://`` export.

Specifications:
- Key URI format (de facto, from Google Authenticator),
  https://github.com/google/google-authenticator/wiki/Key-Uri-Format
  ``otpauth://totp|hotp/<issuer>:<account>?secret=<base32>&issuer=&algorithm=SHA1&digits=6&period=30&counter=``
- The migration export is base64 of a protobuf ``MigrationPayload`` (field 1 repeated ``OtpParameters``:
  1 secret bytes, 2 name, 3 issuer, 4 algorithm, 5 digits, 6 type, 7 counter; then 2 version, 3 batch size,
  4 batch index, 5 batch ID), as published in the open-source exporters, e.g.
  https://github.com/scito/extract_otp_secrets/blob/master/src/google_auth.proto
"""

from __future__ import annotations

import base64
import binascii
import re
import urllib.parse

TYPE = "otpauth"
NOTE = "contains the shared secret: whoever has it can generate the one-time passwords"
ALGORITHMS = {0: None, 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
DIGITS = {0: None, 1: 6, 2: 8}
KINDS = {0: None, 1: "hotp", 2: "totp"}


def _base32_ok(secret: str) -> bool:
    s = secret.upper().rstrip("=")
    if not s or not re.fullmatch(r"[A-Z2-7]+", s):
        return False
    try:
        base64.b32decode(s + "=" * (-len(s) % 8))
    except binascii.Error:
        return False
    return True


def _key_uri(text: str) -> dict:
    parsed = urllib.parse.urlsplit(text)
    query = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
    kind = parsed.netloc.lower()
    label = urllib.parse.unquote(parsed.path.lstrip("/"))
    issuer_in_label, _, account = label.rpartition(":")
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "otp_type": kind,
                    "account": account.strip(), "note": NOTE}
    issuer = query.get("issuer") or issuer_in_label.strip()
    if issuer:
        result["issuer"] = issuer
    if issuer_in_label and query.get("issuer") and issuer_in_label.strip() != query["issuer"]:
        result["warnings"].append(f"issuer {query['issuer']!r} differs from the label prefix {issuer_in_label!r}")
    if kind not in ("totp", "hotp"):
        result["errors"].append(f"unknown OTP type {kind!r}, expected totp or hotp")
    secret = query.get("secret", "")
    result["secret"] = secret
    if not secret:
        result["errors"].append("secret missing")
    elif not _base32_ok(secret):
        result["errors"].append("secret is not base32")
    result["algorithm"] = query.get("algorithm", "SHA1").upper()
    if result["algorithm"] not in ("SHA1", "SHA256", "SHA512"):
        result["warnings"].append(f"unusual algorithm {result['algorithm']}")
    for key, default in (("digits", "6"), ("period", "30"), ("counter", None)):
        value = query.get(key, default)
        if value is None or (key == "period" and kind == "hotp"):
            continue
        if value.isdigit():
            result[key] = int(value)
        else:
            result["errors"].append(f"{key} must be a number, got {value!r}")
    if kind == "hotp" and "counter" not in query:
        result["errors"].append("hotp requires a counter")
    result["valid"] = not result["errors"]
    return result


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(buf) or shift > 63:
            raise ValueError("truncated varint")
        b = buf[pos]
        value |= (b & 0x7F) << shift
        pos += 1
        shift += 7
        if not b & 0x80:
            return value, pos


def _fields(buf: bytes) -> list[tuple[int, int | bytes]]:
    """Protobuf wire format: varints (type 0) and length-delimited fields (type 2) only."""
    out, pos = [], 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
            out.append((number, value))
        elif wire == 2:
            n, pos = _varint(buf, pos)
            if pos + n > len(buf):
                raise ValueError("truncated field")
            out.append((number, buf[pos:pos + n]))
            pos += n
        else:
            raise ValueError(f"unexpected wire type {wire}")
    return out


def _account(buf: bytes) -> dict:
    f = dict(_fields(buf))
    account: dict = {}
    if isinstance(f.get(1), bytes):
        account["secret"] = base64.b32encode(f[1]).decode().rstrip("=")
    for number, key in ((2, "account"), (3, "issuer")):
        if isinstance(f.get(number), bytes):
            account[key] = f[number].decode("utf-8", "replace")
    for number, key, table in ((6, "otp_type", KINDS), (4, "algorithm", ALGORITHMS), (5, "digits", DIGITS)):
        value = table.get(f.get(number, 0)) if isinstance(f.get(number, 0), int) else None
        if value is not None:
            account[key] = value
    if account.get("otp_type") == "hotp" and isinstance(f.get(7), int):
        account["counter"] = f[7]
    return account


def _migration(text: str) -> dict:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(text).query)
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "otp_type": "migration",
                    "accounts": [], "note": NOTE + "; this export holds every listed account"}
    data = query.get("data", [""])[0]
    try:
        payload = base64.b64decode(data + "=" * (-len(data) % 4), validate=True)
        fields = _fields(payload)
        for number, value in fields:
            if number == 1 and isinstance(value, bytes):
                result["accounts"].append(_account(value))
            elif number in (2, 3, 4, 5) and isinstance(value, int):
                result[{2: "version", 3: "batch_size", 4: "batch_index", 5: "batch_id"}[number]] = value
    except (binascii.Error, ValueError) as exc:
        result["errors"].append(f"data cannot be decoded: {exc}")
    if not data:
        result["errors"].append("data parameter missing")
    elif not result["accounts"] and not result["errors"]:
        result["errors"].append("the export contains no accounts")
    result["valid"] = not result["errors"]
    return result


def match(data: bytes, aim: str | None = None) -> dict | None:
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    lower = text.lower()
    if lower.startswith("otpauth-migration://"):
        return _migration(text)
    if lower.startswith("otpauth://"):
        return _key_uri(text)
    return None
