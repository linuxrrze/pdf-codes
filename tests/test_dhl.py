"""DHL return label QR code. All names, addresses and numbers are invented."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers.dhl import dhl_check_digit


def with_check_digit(digits: str) -> str:
    return digits + str(dhl_check_digit(digits))


IDENTCODE = with_check_digit("12345678901")
LEITCODE = with_check_digit("1234512300733")


def label(identcode=IDENTCODE, leitcode=LEITCODE, recipient_postcode="12345", trailing=True) -> bytes:
    fields = ["RON", identcode, "", "DHL RETOURE", "A", "Erika Mustermann", "", "Musterweg 1", "54321",
              "Musterstadt", "Deutschland", "Beispiel GmbH", "Retourenabteilung", "Hauptstraße 7",
              recipient_postcode, "Beispielstadt", "Deutschland", "", "", "", leitcode, identcode, "260131",
              "1-2-3", "7"]
    return "|".join(fields if trailing else fields[:-2]).encode("iso-8859-1")


def test_return_label():
    p = classify(label(), "]Q1")
    assert p["type"] == "dhl_return_label" and p["valid"] and p["warnings"] == [], p["errors"]
    i = p["inferred"]
    assert i["identcode"] == IDENTCODE and i["product"] == "DHL RETOURE" and i["date"] == "2026-01-31"
    assert i["sender"] == {"name": "Erika Mustermann", "street": "Musterweg 1", "postcode": "54321",
                           "city": "Musterstadt", "country": "Deutschland"}
    assert i["recipient"]["street"] == "Hauptstraße 7"  # ISO 8859-1
    assert i["leitcode"] == {"code": LEITCODE, "postcode": "12345", "street_code": "123", "house_number": 7,
                             "product_code": "33", "product": "return"}
    assert i["unknown_fields"] == {"4": "A", "23": "1-2-3", "24": "7"}


def test_check_digits():
    # 1*4 + 2*9 + 3*4 + 4*9 + 5*4 + 6*9 + 7*4 + 8*9 + 9*4 + 0*9 + 1*4 = 284, topped up to 290
    assert dhl_check_digit("12345678901") == 6
    bad_ident = IDENTCODE[:-1] + str((int(IDENTCODE[-1]) + 1) % 10)
    p = classify(label(identcode=bad_ident), "]Q1")
    assert not p["valid"] and "Identcode: check digit" in p["errors"][0]
    bad_leit = LEITCODE[:-1] + str((int(LEITCODE[-1]) + 1) % 10)
    p = classify(label(leitcode=bad_leit), "]Q1")
    assert not p["valid"] and "leitcode" not in p["inferred"]


def test_inconsistencies_are_warnings():
    p = classify(label(recipient_postcode="99999", trailing=False), "]Q1")
    assert p["valid"]
    assert any("postcode" in w for w in p["warnings"]) and any("23 fields" in w for w in p["warnings"])


@pytest.mark.parametrize("payload", [b"RON|1|2|3", b"RONALD|" + b"|" * 24, b"Retoure " + label()])
def test_not_dhl(payload):
    assert classify(payload, "]Q1")["type"] != "dhl_return_label"
