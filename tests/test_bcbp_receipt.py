"""IATA boarding passes and German fiscal receipt QR codes. All personal data is invented."""

from __future__ import annotations

import base64
import hashlib

import pytest

from pdfsieve.codes.classify import classify


def leg(pnr="ABC123", frm="FRA", to="MUC", carrier="LH", flight="0123", day="045", seat="012A", seq="0042",
        conditional=""):
    fixed = (f"{pnr:<7}{frm}{to}{carrier:<3}{flight:<5}{day}Y{seat}{seq:<5}1")
    return fixed + f"{len(conditional):02X}" + conditional


def unique(version="6", issue="6044", doc="B"):
    body = f"0WW{issue}{doc}LH " + " " * 13
    return f">{version}{len(body):02X}{body}"


def repeated(ff="LH 992000000000000 "):
    body = f"220{'1234567890':<10}  LH {ff:<19}20K"
    return f"{len(body):02X}{body}"


def boarding_pass(legs: list[str], name="MUSTERMANN/ERIKA", security="") -> bytes:
    return f"M{len(legs)}{name:<20}E{''.join(legs)}{security}".encode()


def test_single_leg_full():
    data = boarding_pass([leg(conditional=unique() + repeated() + "AIRLINE-DATA")])
    p = classify(data, "]L2")
    assert p["type"] == "iata_bcbp" and p["valid"], p["errors"]
    assert p["passenger_name"] == "MUSTERMANN/ERIKA" and p["electronic_ticket"] is True
    assert p["version"] == "6" and p["document_kind"] == "boarding pass"
    assert p["issue_date"] == {"year_last_digit": 6, "day_of_year": 44}
    (only,) = p["legs"]
    assert (only["from"], only["to"], only["carrier"], only["flight_number"]) == ("FRA", "MUC", "LH", "123")
    assert (only["day_of_year"], only["seat"], only["pnr"]) == (45, "012A", "ABC123")
    assert only["airline_numeric_code"] == "220" and only["marketing_carrier"] == "LH"
    assert only["airline_use"] == "AIRLINE-DATA"


def test_two_legs_and_security_data():
    data = boarding_pass([leg(conditional=unique() + repeated()),
                          leg(frm="MUC", to="JFK", flight="0410", conditional=repeated())],
                         security="^1" + "08" + "SIGNATUR")
    p = classify(data, "]z0")
    assert p["valid"], p["errors"]
    assert [(l["from"], l["to"], l["flight_number"]) for l in p["legs"]] == [("FRA", "MUC", "123"),
                                                                         ("MUC", "JFK", "410")]
    assert p["security_data_type"] == "1" and p["security_data_length"] == 8


def test_mandatory_only_and_itinerary_receipt():
    p = classify(boarding_pass([leg()]), "]L2")
    assert p["valid"] and p["legs"][0]["seat"] == "012A" and "version" not in p
    receipt = boarding_pass([leg(seat="    ", seq="", conditional=unique(doc="I"))])
    assert classify(receipt, "]L2")["document_kind"] == "itinerary receipt"


@pytest.mark.parametrize("data, error", [
    (boarding_pass([leg()])[:-1] + b"X", "hex"),                 # size field not hex
    (boarding_pass([leg(conditional="")])[:40] + b" " * 30, "hex"),
    (boarding_pass([leg(conditional=">6FF")]), "unique conditional data"),  # size larger than the data
    (b"M2" + boarding_pass([leg()])[2:], "PNR".lower()),         # second leg missing
])
def test_malformed_boarding_pass(data, error):
    p = classify(data, "]L2")
    assert p["type"] == "iata_bcbp" and not p["valid"]
    assert any(error in e for e in p["errors"]), p["errors"]


def test_not_bcbp():
    assert classify(b"M1 too short", "]L2")["type"] != "iata_bcbp"
    assert classify(b"Mailing list", "]L2")["type"] != "iata_bcbp"


# The example from DSFinV-K 2.4, Anhang I (public specification).
PUBKEY = ("BBXNYQErM4d9sk9Iy+0T6A4sdTocijml5X78Gq/At2uXTcs/3bZNNpyuHd+dpmY59yLh0xZcr9osHhkDAxsQumgjmtb3d9GIVnTaPCs"
          "lEki84P1iHPiHKHfcszeQajPk3A==")
SPEC_EXAMPLE = ("V0;AMA-2642;Kassenbeleg-V1;Beleg^4.05_3.00_0.00_0.00_0.00^7.05:Bar;13;44131;2019-11-22T11:29:48.000Z;"
                "2019-11-22T11:29:49.000Z;ecdsa-plain-SHA384;unixTime;K8zsZ6NjsBzo/Yd3Hba84aH3oT+c4Og5VcfJ7s6Dxz7UmAwt"
                "cKmzW16OkS/lm8pDE/37JHoRlYofUTLNF+9bY5Jv7C2P4nuEaHwlVarbiJs3bYlgQmIXQDZnf+8FhfBm;" + PUBKEY)


def test_receipt_spec_example():
    p = classify(SPEC_EXAMPLE.encode(), "]Q1")
    assert p["type"] == "kassensichv_receipt" and p["valid"], p["errors"]
    assert (p["register_serial"], p["process_type"], p["transaction_number"]) == ("AMA-2642", "Kassenbeleg-V1", "13")
    assert p["signature_algorithm"] == "ecdsa-plain-SHA384" and p["log_time"] == "2019-11-22T11:29:49.000Z"
    assert p["receipt"] == {"transaction_type": "Beleg",
                            "gross_sales": {"standard": "4.05", "reduced": "3.00", "average_24_1_3": "0.00",
                                            "average_24_1_1": "0.00", "zero": "0.00"},
                            "gross_total": "7.05",
                            "payments": [{"amount": "7.05", "type": "Bar", "currency": "EUR"}]}
    assert p["tse_serial"] == hashlib.sha256(base64.b64decode(PUBKEY)).hexdigest()
    assert p["warnings"] == [] and p["signature_verified"] is None


def test_receipt_foreign_currency_and_mismatch():
    foreign = SPEC_EXAMPLE.replace("Beleg^4.05_3.00_0.00_0.00_0.00^7.05:Bar",
                                   "Beleg^75.33_7.99_0.00_0.00_0.00^10.00:Bar_5.00:Bar:CHF_64.30:Unbar")
    p = classify(foreign.encode())
    assert p["receipt"]["payments"][1] == {"amount": "5.00", "type": "Bar", "currency": "CHF"}
    assert p["warnings"] == []  # sums are only compared when all payments are in EUR
    mismatch = SPEC_EXAMPLE.replace("^7.05:Bar", "^9.99:Bar")
    assert "differ" in classify(mismatch.encode())["warnings"][0]


def test_receipt_order_with_semicolons_in_process_data():
    order = SPEC_EXAMPLE.replace("Kassenbeleg-V1;Beleg^4.05_3.00_0.00_0.00_0.00^7.05:Bar",
                                 'Bestellung-V1;2;"Eisbecher ""Himbeere""";3.99\r1;"Eiskaffee";2.99')
    p = classify(order.encode())
    assert p["valid"] and p["transaction_number"] == "13"  # fields after processData still line up
    assert p["order"]["items"] == [{"quantity": "2", "description": 'Eisbecher "Himbeere"', "price": "3.99"},
                                   {"quantity": "1", "description": "Eiskaffee", "price": "2.99"}]


@pytest.mark.parametrize("change, error", [
    (lambda s: s.replace(";13;", ";x13;"), "transaction_number"),
    (lambda s: s.replace(PUBKEY, "not base64!"), "public key"),
    (lambda s: s.replace("4.05_3.00", "4.05"), "five amounts"),
    (lambda s: s.replace("7.05:Bar", "7.05:Card"), "malformed payment"),
])
def test_receipt_errors(change, error):
    p = classify(change(SPEC_EXAMPLE).encode())
    assert p["type"] == "kassensichv_receipt" and not p["valid"]
    assert any(error in e for e in p["errors"]), p["errors"]


def test_not_receipt():
    assert classify(b"V0;too;few;fields")["type"] != "kassensichv_receipt"
