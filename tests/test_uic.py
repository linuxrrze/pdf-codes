"""UIC 918.3 rail tickets. The ticket below is invented and carries a dummy signature."""

from __future__ import annotations

import zlib

import pytest

from pdfsieve.codes.classify import classify


def record(rid: str, version: str, body: bytes) -> bytes:
    return rid.encode() + version.encode() + f"{len(body) + 12:04d}".encode() + body


def tlay_field(line, col, text):
    data = text.encode()
    return f"{line:02d}{col:02d}01{len(text):02d}0{len(data):04d}".encode() + data


def ticket(version: str = "01", records: bytes | None = None, compressed: bytes | None = None) -> bytes:
    if records is None:
        u_head = record("U_HEAD", "01", b"0080ABC12345" + b"\0" * 12 + b"010120261230" + b"0DEDE")
        sblocks = b"S0230016Erika Mustermann" + b"S0090005" + b"1-0-0"
        bl = record("0080BL", "03", b"02" + b"1" + b"0201202602012026" + b"0123456789" + b"02" + sblocks)
        fields = [tlay_field(6, 13, "Nürnberg"), tlay_field(6, 34, "München"), tlay_field(0, 12, "ICE Fahrkarte")]
        tlay = record("U_TLAY", "01", b"RCT2" + f"{len(fields):04d}".encode() + b"".join(fields))
        records = u_head + bl + tlay
    if compressed is None:
        compressed = zlib.compress(records)
    signature = b"\x30\x2c" + b"\x11" * 42 + b"\0" * (6 if version == "01" else 20)
    return b"#UT" + version.encode() + b"0080" + b"00001" + signature + f"{len(compressed):04d}".encode() + compressed


def test_full_ticket():
    p = classify(ticket(), "]z0")
    assert p["type"] == "uic_ticket" and p["valid"], p["errors"]
    assert (p["issuer_code"], p["issuer"], p["key_id"]) == ("0080", "Deutsche Bahn", "00001")
    assert [r["id"] for r in p["records"]] == ["U_HEAD", "0080BL", "U_TLAY"]
    assert p["header"]["order_number"] == "ABC12345"
    assert p["header"]["created"] == "2026-01-01T12:30"
    db = p["deutsche_bahn"]
    assert db["orders"] == [{"valid_from": "2026-01-02", "valid_to": "2026-01-02", "serial": "0123456789"}]
    assert db["fields"] == {"Personenname": "Erika Mustermann", "Passagiere": "1-0-0"}
    texts = [f["text"] for f in p["layout"]["fields"]]
    assert texts == ["ICE Fahrkarte", "Nürnberg", "München"]  # sorted by line, column; UTF-8 kept
    assert p["signature_verified"] is None and p["warnings"] == []


def test_version_02_has_longer_signature():
    p = classify(ticket(version="02"), "]z0")
    assert p["valid"] and p["header"]["order_number"] == "ABC12345"


def test_unknown_record_is_listed_with_warning():
    p = classify(ticket(records=record("U_FLEX", "13", b"\x01\x02")), "]z0")
    assert p["valid"] and p["records"][0]["id"] == "U_FLEX"
    assert "not decoded" in p["warnings"][0]


@pytest.mark.parametrize("data, error", [
    (ticket(version="07"), "unknown container version"),
    (ticket(compressed=b"not zlib at all"), "zlib"),
    (ticket()[:-10], "header says"),
    (ticket(records=b"U_HEAD01" + b"9999" + b"x"), "does not fit"),
    (b"#UT01ABCD", "compressed length"),
])
def test_broken_tickets_are_reported(data, error):
    p = classify(data, "]z0")
    assert p["type"] == "uic_ticket" and not p["valid"]
    assert any(error in e for e in p["errors"]), p["errors"]


def test_decompression_bomb_is_refused():
    bomb = zlib.compress(b"\0" * (4 * 1024 * 1024), 9)
    p = classify(ticket(compressed=bomb), "]z0")
    assert not p["valid"] and "exceeds" in p["errors"][0]
