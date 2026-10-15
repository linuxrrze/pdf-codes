from __future__ import annotations

import pytest

from code_tools.cli import code_parse
from code_tools.codes.classify import PARSERS, classify
from code_tools.codes.parsers import epc, gs1, swiss_qr
from code_tools.codes.parsers.common import iban_valid, rf_reference_valid

EPC = ("BCD\n002\n1\nSCT\nBFSWDE33BER\nWikimedia Foerdergesellschaft\nDE33100205000001194700\nEUR123.4\n"
       "CHAR\n\nSpende fuer Wikipedia")

SWISS = "\n".join([
    "SPC", "0200", "1", "CH4431999123000889012",
    "S", "Robert Schneider AG", "Rue du Lac", "1268", "2501", "Biel", "CH",
    "", "", "", "", "", "", "",
    "1949.75", "CHF",
    "S", "Pia-Maria Rutschmann-Schnyder", "Grosse Marktgasse", "28", "9400", "Rorschach", "CH",
    "QRR", "210000000003139471430009017", "Order dated 18.06.2020", "EPD",
    "//S1/10/10201409/11/200701/20/140.000-53/30/102673831/31/200615/32/7.7/33/7.7:139.40/40/0:30",
    "Name AV1: UV;UltraPay005;12345", "Name AV2: XY;XYService;54321",
])


def test_checksums():
    assert iban_valid("DE33100205000001194700")
    assert iban_valid("DE33 1002 0500 0001 1947 00")
    assert not iban_valid("DE33100205000001194701")
    assert not iban_valid("DE3310020500000119470")  # wrong length for DE
    assert rf_reference_valid("RF18539007547034")
    assert not rf_reference_valid("RF19539007547034")
    assert swiss_qr.qr_reference_valid("210000000003139471430009017")
    assert not swiss_qr.qr_reference_valid("210000000003139471430009018")


def test_epc_valid():
    p = epc.match(EPC.encode())
    assert p["valid"], p["errors"]
    assert p["iban"] == "DE33100205000001194700"
    assert p["bic"] == "BFSWDE33BER"
    assert p["amount"] == "123.40" and p["currency"] == "EUR"
    assert p["purpose"] == "CHAR"
    assert p["text"] == "Spende fuer Wikipedia"


def test_epc_crlf_and_latin1():
    data = EPC.replace("\n1\n", "\n2\n", 1).replace("Foerdergesellschaft", "Fördergesellschaft")
    p = epc.match(data.replace("\n", "\r\n").encode("iso-8859-1"))
    assert p["valid"], p["errors"]
    assert p["name"] == "Wikimedia Fördergesellschaft"


@pytest.mark.parametrize("mutate, error", [
    (lambda s: s.replace("DE331002", "DE341002"), "invalid IBAN"),
    (lambda s: s.replace("\n002\n", "\n003\n"), "unknown version"),
    (lambda s: s.replace("EUR123.4", "EUR12.345"), "malformed amount"),
    (lambda s: s.replace("\n002\n", "\n001\n").replace("BFSWDE33BER", ""), "BIC is required"),
    (lambda s: s.replace("\nCHAR\n\n", "\nCHAR\nRF18539007547034\n"), "mutually exclusive"),
])
def test_epc_invalid_is_still_epc(mutate, error):
    p = epc.match(mutate(EPC).encode())
    assert p["type"] == "epc" and not p["valid"]
    assert any(error in e for e in p["errors"]), p["errors"]


def test_epc_decimal_comma_is_a_warning():
    # Real-world shape: version 001, CRLF, decimal comma, trailing empty lines.
    data = ("BCD\r\n001\r\n1\r\nSCT\r\nBFSWDE33BER\r\nWikimedia Foerdergesellschaft\r\n"
            "DE33100205000001194700\r\nEUR482,57\r\n\r\n\r\nRechnung 4711\r\n\r\n")
    p = epc.match(data.encode())
    assert p["valid"], p["errors"]
    assert p["amount"] == "482.57" and p["currency"] == "EUR"
    assert p["text"] == "Rechnung 4711"
    assert any("decimal comma" in w for w in p["warnings"])
    assert epc.match(EPC.encode())["warnings"] == []


@pytest.mark.parametrize("amount", ["EUR1.234,56", "EUR12,345", "EUR12,", "EUR,5"])
def test_epc_other_amount_formats_still_rejected(amount):
    p = epc.match(EPC.replace("EUR123.4", amount).encode())
    assert not p["valid"] and any("malformed amount" in e for e in p["errors"]), p


def test_epc_truncated_fields():
    p = epc.match(b"BCD\n002\n1\nSCT\n")
    assert p["type"] == "epc" and not p["valid"]
    assert any("IBAN" in e for e in p["errors"])


def test_swiss_valid():
    p = swiss_qr.match(SWISS.encode())
    assert p["valid"], p["errors"]
    assert p["qr_iban"] is True
    assert p["amount"] == "1949.75" and p["currency"] == "CHF"
    assert p["creditor"]["name"] == "Robert Schneider AG"
    assert p["debtor"]["town"] == "Rorschach"
    assert p["reference_type"] == "QRR"
    assert p["alternative_procedures"] == ["Name AV1: UV;UltraPay005;12345", "Name AV2: XY;XYService;54321"]


@pytest.mark.parametrize("mutate, error", [
    (lambda s: s.replace("210000000003139471430009017", "210000000003139471430009018"), "invalid QR reference"),
    (lambda s: s.replace("\nQRR\n", "\nNON\n"), "QR-IBAN requires"),
    (lambda s: s.replace("\nEPD", "\nEPX"), "trailer"),
    (lambda s: s.replace("\nCHF\n", "\nUSD\n"), "currency"),
    (lambda s: "\n".join(s.split("\n")[:20]), "lines"),
])
def test_swiss_invalid(mutate, error):
    p = swiss_qr.match(mutate(SWISS).encode())
    assert p["type"] == "swiss_qr" and not p["valid"]
    assert any(error in e for e in p["errors"]), p["errors"]


def test_gs1_raw_element_string_with_group_separators():
    p = gs1.match(b"0109506000134352172512311" + b"0ABC\x1d21XYZ", "]d2")
    assert p["valid"], p["errors"]
    assert [(e["ai"], e["value"]) for e in p["elements"]] == [
        ("01", "09506000134352"), ("17", "251231"), ("10", "ABC"), ("21", "XYZ")]
    assert p["elements"][1]["date"] == "2025-12-31"
    assert p["hri"] == "(01)09506000134352(17)251231(10)ABC(21)XYZ"


def test_gs1_hri_and_bad_check_digit():
    assert gs1.match(b"(01)09506000134352(3103)001250")["elements"][1]["number"] == 1.25
    bad = gs1.match(b"(01)09506000134353")
    assert not bad["valid"] and "check digit" in bad["errors"][0]


def test_gs1_needs_marker():
    # A plain number is not GS1 unless the decoder says so.
    assert gs1.match(b"0109506000134352", None) is None
    assert gs1.match(b"]C10109506000134352", None)["valid"]


@pytest.mark.parametrize("payload, kind, field, value", [
    (b"BEGIN:VCARD\nVERSION:3.0\nFN:Erika Mustermann\nTEL;TYPE=work:+49 30 1234\nEND:VCARD", "vcard", "name",
     "Erika Mustermann"),
    (b"MECARD:N:Doe,John;TEL:+1234;EMAIL:j@x.org;;", "mecard", "emails", ["j@x.org"]),
    (b"WIFI:T:WPA;S:my\\;net;P:secret;H:true;;", "wifi", "ssid", "my;net"),
    (b"mailto:info@example.org?subject=Hello", "mailto", "subject", "Hello"),
    (b"tel:+49301234567", "tel", "number", "+49301234567"),
    (b"SMSTO:+491701234567:Hi there", "sms", "body", "Hi there"),
    (b"geo:49.5973,11.0049", "geo", "latitude", 49.5973),
    (b"https://www.fau.de/path?q=1", "url", "host", "www.fau.de"),
    (b"HC1:NCFOXN%TS3DH3ZSUZK", "eu_dcc", "valid", True),
    (b'<MP v="026" U="..."><P g="Max"/></MP>', "medication_plan", "version", "026"),
])
def test_generic(payload, kind, field, value):
    p = classify(payload)
    assert p["type"] == kind
    assert p[field] == value


def franking(cents: int, dddyy: int, number: int, tail: bytes = b"\x11\x22\x33\x44") -> bytes:
    """42-byte franking payload with the inferred field positions; constant parts are made up."""
    return (b"DEA\x12\x00\x01\xaa\xbb\xcc\xdd" + cents.to_bytes(2, "big") + dddyy.to_bytes(2, "big")
            + b"\x00\x01\x00" + number.to_bytes(2, "big") + b"\xe9\x06\x59\x00" + b" " * 12
            + b"A\xc4\x02" + tail)


def test_deutsche_post_franking():
    data = franking(95, 28226, 13878)
    assert len(data) == 42
    p = classify(data, "]d1")
    assert p["type"] == "deutsche_post_franking" and p["valid"]
    assert p["inferred"]["postage"] == "0.95"
    assert p["inferred"]["date"] == "2026-10-09"  # day 282 of 2026
    assert p["inferred"]["printed_number"] == 13878
    assert p["inferred"]["printed_id_start"] == "E90659"
    assert classify(data)["type"] == "deutsche_post_franking"  # code-parse: symbology unknown
    assert classify(data, "]Q1")["type"] == "raw"  # Deutsche Post uses DataMatrix only
    assert classify(b"DEAR customer, thank you", "]d1")["type"] == "raw"
    assert classify(b"DEA", "]d1")["type"] == "raw"


@pytest.mark.parametrize("dddyy, date", [(16226, "2026-06-11"), (27226, "2026-09-29"), (36524, "2024-12-30"),
                                         (36624, "2024-12-31"), (36626, None), (126, "2026-01-01"), (26, None)])
def test_franking_date(dddyy, date):
    assert classify(franking(110, dddyy, 1), "]d1")["inferred"]["date"] == date


def test_franking_version_byte_and_sender_reference():
    # Layout seen on letters from 2017-2019: no signature block, a sender reference in ASCII digits instead.
    data = franking(70, 34418, 5392)
    data = data[:4] + b"\x26" + data[5:22] + b"\x00" + b"12345670000005392" + b"\x00\x00"
    assert len(data) == 42
    inferred = classify(data, "]d1")["inferred"]
    assert (inferred["postage"], inferred["date"]) == ("0.70", "2018-12-10")
    assert inferred["version_byte"] == "26"
    assert inferred["sender_reference"] == "12345670000005392"
    assert "sender_reference" not in classify(franking(95, 28226, 1), "]d1")["inferred"]


def test_franking_other_length_has_no_inferred_fields():
    p = classify(franking(95, 28226, 1) + b"\x00", "]d1")
    assert p["type"] == "deutsche_post_franking" and "inferred" not in p


# Layout like a real eP code (prefix, digits, base64 blocks, digits); the content is made up.
EP = b"eP12345678" + b"QUJDREVGR0hJSktMTU5PUA==" + b"7" + b"UVJTVFVWV1hZWmFiY2RlZmdoaWprbG1ub3BxcnN0dXY=" + b"9876543210"


def test_pkv_invoice_code():
    p = classify(EP, "]d1")
    assert p["type"] == "pkv_invoice_code" and p["code"] == "eP"
    assert p["name"] == "elektronischer Positionscode"
    assert classify(b"eA9" + EP[3:], "]d1")["code"] == "eA"
    assert classify(EP)["type"] == "pkv_invoice_code"  # code-parse: symbology unknown
    assert classify(EP, "]Q1")["type"] == "raw"  # the scheme uses DataMatrix
    assert classify(b"eP is a short text", "]d1")["type"] == "raw"
    assert classify(b"ePrivat123", "]d1")["type"] == "raw"


def test_pkv_invoice_code_older_layout():
    old = (b"eP123456789012345678_1_au_260105123" + b"UVJTVFVWV1hZWmFiY2RlZmdoaWprbG1ub3BxcnN0dXY="
           + b"1001345678")
    p = classify(old, "]d1")
    assert p["type"] == "pkv_invoice_code" and p["code"] == "eP"


def test_raw_fallback_and_ordering():
    assert classify(b"just some text")["type"] == "raw"
    assert classify(b"\x00\xff\xfe binary")["type"] == "raw"
    assert classify(b"http://has space")["type"] == "raw"
    # Headers are distinct, so each sample is claimed by exactly one parser.
    samples = [EPC.encode(), SWISS.encode(), b"WIFI:S:x;;", b"https://x.org"]
    for sample in samples:
        claims = [name for name, parser in PARSERS if parser(sample, None) is not None]
        assert len(claims) == 1, claims


def test_code_parse_cli(invoke):
    data = EPC.encode() + b"\0" + SWISS.encode() + b"\0" + b"hello\0"
    r = invoke(code_parse.main, "-0", stdin=data)
    assert r.code == 0
    assert [rec["payload"]["type"] for rec in r.records] == ["epc", "swiss_qr", "raw"]
    r = invoke(code_parse.main, stdin=b"hello\nworld\n")
    assert r.code == 1 and len(r.records) == 2
    r = invoke(code_parse.main, "--aim", "]d2", stdin=b"0109506000134352\n")
    assert r.records[0]["payload"]["type"] == "gs1"


def test_crashing_parser_becomes_an_error(monkeypatch):
    from code_tools.codes import classify as classify_module

    def broken(data, aim=None):
        if data.startswith(b"BOOM"):
            raise IndexError("list index out of range")
        return None

    monkeypatch.setattr(classify_module, "PARSERS", [("broken", broken), *classify_module.PARSERS])
    p = classify_module.classify(b"BOOM https://example.org", "]Q1")
    assert p == {"type": "raw", "valid": False, "warnings": [],
                 "errors": ["internal error in the broken parser: IndexError: list index out of range"]}
    assert classify_module.classify(b"https://example.org", "]Q1")["type"] == "url"  # others unaffected

    monkeypatch.setattr(classify_module, "PARSERS", [("no_type", lambda data, aim=None: {"valid": True})])
    assert "internal error in the no_type parser: KeyError" in classify_module.classify(b"x")["errors"][0]


def test_icalendar_event():
    # ZXing writes events without the VCALENDAR wrapper.
    data = (b"BEGIN:VEVENT\r\nSUMMARY:Team meeting\\, room 2\r\n"
            b"DTSTART:20261015T090000Z\r\nDTEND:20261015T100000Z\r\n"
            b"LOCATION:Erlangen\r\nDESCRIPTION:Agenda:\\nitem one\r\nEND:VEVENT\r\n")
    p = classify(data, "]Q1")
    assert p["type"] == "icalendar" and p["valid"], p["errors"]
    assert p["events"] == [{"summary": "Team meeting, room 2", "dtstart": "2026-10-15T09:00:00Z",
                            "dtend": "2026-10-15T10:00:00Z", "location": "Erlangen",
                            "description": "Agenda:\nitem one"}]


def test_icalendar_calendar_with_dates_and_problems():
    data = (b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20261224\nEND:VEVENT\n"
            b"BEGIN:VEVENT\nSUMMARY:Call\nDTSTART;TZID=Europe/Berlin:20261015T090000\nEND:VEVENT\nEND:VCALENDAR")
    p = classify(data)
    assert p["valid"] and [e["dtstart"] for e in p["events"]] == ["2026-12-24", "2026-10-15T09:00:00 (Europe/Berlin)"]
    p = classify(b"BEGIN:VEVENT\nSUMMARY:No start\n")
    assert p["type"] == "icalendar" and not p["valid"]
    assert p["errors"] == ["missing END:VEVENT", "event 1: DTSTART missing"]
    assert classify(b"BEGIN:VCALENDAR\nEND:VCALENDAR")["errors"] == ["no event (VEVENT)"]
    assert classify(b"BEGIN:VCARD\nFN:x\nEND:VCARD")["type"] == "vcard"
