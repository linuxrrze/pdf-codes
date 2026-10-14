"""Beihilfe form QR codes. Names, numbers and IDs are invented."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify

APPLICATION = "H001;V 04.2019;0f8e9d7c-1a2b-4c3d-8e9f-0123456789ab;2;12345678;Mustermann;Erika;".encode()


def test_application_page():
    p = classify(APPLICATION, "]Q1")
    assert p["type"] == "beihilfe_form" and p["valid"] and p["warnings"] == [], p["errors"]
    i = p["inferred"]
    assert (i["document"], i["form"], i["form_version"], i["page"]) == ("application", "H001", "2019-04", 2)
    assert (i["person_number"], i["surname"], i["first_name"]) == ("12345678", "Mustermann", "Erika")
    assert i["document_id"] == "0f8e9d7c-1a2b-4c3d-8e9f-0123456789ab" and "caveat" in i


def test_notice_and_old_form():
    p = classify(b"X_" + APPLICATION.replace(b"V 04.2019", b"V 01.2018"), "]Q1")
    assert p["inferred"]["document"] == "notice" and p["inferred"]["form_version"] == "2018-01"
    old = classify(b"H001;\r\n01.2013;", "]Q1")
    assert old["type"] == "beihilfe_form" and old["valid"] and old["inferred"]["form_version"] == "2013-01"
    assert "page" not in old["inferred"]
    assert classify("H001;V 04.2019;0f8e9d7c-1a2b-4c3d-8e9f-0123456789ab;1;12345678;Müller;Jürgen;".encode(
        "iso-8859-1"), "]Q1")["inferred"]["surname"] == "Müller"


def test_problems():
    p = classify(APPLICATION.replace(b";2;", b";two;"), "]Q1")
    assert not p["valid"] and "page" in p["errors"][0]
    p = classify(APPLICATION.replace(b"0f8e9d7c-", b"0f8e9d7c"), "]Q1")
    assert not p["valid"] and "UUID" in p["errors"][0]
    p = classify(APPLICATION.replace(b"Erika;", b"Erika;extra;"), "]Q1")
    assert p["valid"] and "8 fields" in p["warnings"][0]


@pytest.mark.parametrize("payload, aim", [
    (b"H001;", "]Q1"),                     # header alone
    (b"H001;hello;world", "]Q1"),          # no form version
    (APPLICATION, "]d1"),                  # not a QR code
    (b"XH001;V 04.2019;", "]Q1"),
])
def test_not_beihilfe(payload, aim):
    assert classify(payload, aim)["type"] != "beihilfe_form"
