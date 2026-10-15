"""ISO/IEC 15434 envelopes and IFA PPN codes. 110375286414 is IFA's published sample PPN; batches and serial
numbers are invented."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers.iso15434 import ppn_check, pzn_valid

RS, GS, EOT = "\x1e", "\x1d", "\x04"


def envelope(*fields: str, fmt: str = "06", trailer: str = RS + EOT) -> bytes:
    return ("[)>" + RS + fmt + GS + GS.join(fields) + trailer).encode("latin-1")


PACK = envelope("9N110375286414", "1T12345AB", "D261100", "S1234567890ABC")


def test_securpharm_pack():
    p = classify(PACK, "]d1")
    assert p["type"] == "iso15434" and p["valid"] and p["warnings"] == [], p["errors"]
    assert p["pharma"] == {"ppn": "110375286414", "pzn": "03752864", "batch": "12345AB", "expiry": "2026-11",
                           "serial": "1234567890ABC"}
    elements = p["envelopes"][0]["elements"]
    assert [e["di"] for e in elements] == ["9N", "1T", "D", "S"] and elements[0]["name"] == "PPN"


def test_check_digits():
    assert ppn_check("110375286414") == "14"
    assert pzn_valid("03752864") and not pzn_valid("03752865")
    p = classify(envelope("9N110375286415", "1TX", "D261231", "S1"))
    assert not p["valid"] and "PPN check digits" in p["errors"][0]
    p = classify(envelope("9N110375286414", "1TX", "D261331", "S1"))
    assert not p["valid"] and "expiry" in p["errors"][0]
    p = classify(envelope("9N110375286414", "8P04150123456782", "1TX", "D261231", "S1"))
    assert p["valid"] and p["pharma"]["gtin"] == "04150123456782" and p["pharma"]["expiry"] == "2026-12-31"


def test_missing_parts_are_warnings():
    p = classify(envelope("9N110375286414"))
    assert p["valid"] and "batch, expiry, serial" in p["warnings"][0]
    p = classify(envelope("9N110375286414", "1TX", "D261231", "S1", trailer=""))
    assert p["valid"] and "EOT" in p["warnings"][0]


def test_other_formats():
    p = classify(envelope("1PABC-123", "Q100", "4LDE"))
    assert p["valid"] and "pharma" not in p
    assert [(e["di"], e["value"]) for e in p["envelopes"][0]["elements"]] == [("1P", "ABC-123"), ("Q", "100"),
                                                                             ("4L", "DE")]
    p = classify(envelope("0104150123456782", "10ABC", fmt="05"))
    assert p["valid"] and [e["ai"] for e in p["envelopes"][0]["elements"]] == ["01", "10"]
    p = classify(envelope("96", "1Z123", "840", fmt="01"))  # UPS MaxiCode style
    assert p["envelopes"][0]["fields"] == ["96", "1Z123", "840"]


@pytest.mark.parametrize("payload", [b"[)>", b"[)> 06 9N110375286414", b"text [)>\x1e06"])
def test_not_iso15434(payload):
    assert classify(payload, "]d1")["type"] != "iso15434"
