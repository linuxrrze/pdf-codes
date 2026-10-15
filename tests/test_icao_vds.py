"""ICAO Visible Digital Seals. The two byte strings below are the worked examples (specimen data) of BSI TR-03137
Annexes C and D; the other seals are built here from invented values."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers.icao_vds import c40_decode

ARRIVAL = bytes.fromhex(
    "dc026abc6d32c8a519fc0f71341145f4fd020230a5621353d9a275735bd4134bc54913"
    "3c133c133c133c133ca32519a519a4344a5e681ae7204b20d532cf4b7c133c133f03"
    "0820d5201019a51aeaff404a1f218ca4392647ecff6c8abf9e796a78eebe0b1ac8cc"
    "25c4ee17eed961d1189091358d7d616f1a517abc747f6c4490ff159d4dcf50248b00b1e32e9e7805e7")
SIC = bytes.fromhex(
    "dc026abc6d32c8a519fc0f7134116d04fc0401083fee456d2de019a8020b506572736368776569c39f03054f736361720413"
    "4ac3a2636f62c3a96e69646963747572697573ff40582ed05cb05049b4fe49744d5e70a1982f8b7afb1e90259ce47ba9907e"
    "fcf59483f0a0b421ec760d6fd2284bbac37e136f1e3be6e14a6f6bc012110cff919d0f")
C40 = {" ": 3, **{str(i): i + 4 for i in range(10)}, **{chr(65 + i): i + 14 for i in range(26)}}


def c40(text: str) -> bytes:
    text = text.replace("<", " ")
    out = b""
    for i in range(0, len(text), 3):
        chunk = text[i:i + 3]
        if len(chunk) == 1:
            out += bytes([0xFE, ord(chunk) + 1])
            continue
        u = [C40[c] for c in chunk] + [0] * (3 - len(chunk))
        out += (1600 * u[0] + 40 * u[1] + u[2] + 1).to_bytes(2, "big")
    return out


def date(month: int, day: int, year: int) -> bytes:
    return int(f"{month:02d}{day:02d}{year}").to_bytes(3, "big")


def seal(ref: int, category: int, features: list[tuple[int, bytes]], version: int = 0x03,
         signer: str = "DETS", cert: str = "1A", signature: bytes = b"\x11" * 64) -> bytes:
    if version == 0x03:
        header = c40(f"{signer}{len(cert):02X}{cert}")
    else:
        header = c40(f"{signer}{cert:0>5}")
    data = b"\xdc" + bytes([version]) + c40("D<<") + header + date(1, 15, 2026) + date(1, 16, 2026)
    data += bytes([ref, category])
    for tag, value in features:
        data += bytes([tag, len(value)]) + value
    return data + b"\xff" + bytes([len(signature)]) + signature


MRZ = "ARD<<MUSTERMANN<<ERIKA<<<<<<<<<<<<<<<" + "C01X00T478D<<6408125F2702283<<<<<<<4"


def test_c40_examples_from_the_specification():
    assert c40_decode(bytes.fromhex("eb0466a9")) == "XK CD"
    assert c40_decode(bytes.fromhex("eb11fe45")) == "XKCD"
    assert c40_decode(bytes.fromhex("62d719c9")) == "BSI01"
    assert c40("XK<CD") == bytes.fromhex("eb0466a9") and c40("XKCD") == bytes.fromhex("eb11fe45")
    assert c40_decode(b"\x00\x00") is None and c40_decode(b"\xfe") is None


def test_arrival_attestation_worked_example():
    p = classify(ARRIVAL, "]d1")
    assert p["type"] == "icao_vds" and p["valid"] and p["warnings"] == [], p["errors"]
    assert (p["version"], p["issuing_country"], p["signer"], p["certificate_reference"]) == (3, "D<<", "DETS", "00027")
    assert (p["issue_date"], p["signature_date"]) == ("2020-01-01", "2020-01-13")
    assert p["document"] == "arrival_attestation" and p["signature_length"] == 64
    assert p["features"] == {"mrz": ["MED<<MUSTERMANN<<ERIK<<<<<<<<<<<<<<<", "M0000000<4ALB0308212M1604128<<<<<<<2"],
                             "azr_number": "160113000085"}
    assert "personal data" in p["note"]


def test_social_insurance_card_worked_example():
    p = classify(SIC)
    assert p["valid"] and p["document"] == "social_insurance_card"
    assert p["features"] == {"social_insurance_number": "65170839J003", "surname": "Perschweiß",
                             "first_name": "Oscar", "birth_name": "Jâcobénidicturius"}


def test_residence_permit_version_4():
    p = classify(seal(0xFB, 0x06, [(2, c40(MRZ)), (3, c40("C01X00T47"))], cert="1A2B3"), "]d1")
    assert p["valid"] and p["warnings"] == [], p["errors"]
    assert (p["version"], p["signer"], p["certificate_reference"]) == (4, "DETS", "1A2B3")
    assert p["document"] == "residence_permit"
    assert p["features"] == {"mrz": [MRZ[:36], MRZ[36:]], "passport_number": "C01X00T47"}


def test_address_sticker_and_visa():
    p = classify(seal(0xF9, 0x08, [(1, c40("T22000129")), (2, c40("05314000")), (3, c40("53175 HEINEMANNSTR 11"))]))
    assert p["document"] == "address_sticker_id_card"
    assert p["features"]["address"] == "53175 HEINEMANNSTR 11"
    p = classify(seal(0x5D, 0x01, [(2, c40(MRZ)), (3, b"\x01"), (4, b"\x5a\x00\x00"), (5, c40("C01X00T47"))]))
    assert p["document"] == "visa"
    assert p["features"]["number_of_entries"] == 1
    assert p["features"]["duration_of_stay"] == {"days": 90, "months": 0, "years": 0}


def test_meldebescheinigung_profile():
    uuid = bytes.fromhex("9a4223406d374ef99e2cf95e31a23846")
    features = [(0, uuid), (4, "Mustermann".encode()), (6, "Erika".encode()), (12, "Köln".encode()), (99, b"x")]
    p = classify(seal(0x01, 0xC8, features))
    assert p["valid"] and p["document"] == "administrative_document_v8" and p["profile"] == "Meldebescheinigung"
    assert p["features"] == {"profile_id": uuid.hex(), "surname": "Mustermann", "first_name": "Erika", "city": "Köln"}
    assert p["unknown_features"] == [{"tag": 99, "hex": "78", "utf8": "x"}]


def test_version_byte_with_the_other_header_layout():
    # Some arrival attestations say version 4 but use the fixed version 3 layout.
    data = bytearray(ARRIVAL)
    data[1] = 0x03
    p = classify(bytes(data), "]d1")
    assert p["valid"] and p["certificate_reference"] == "00027"
    assert "version 3 layout" in p["warnings"][0]


def test_problems():
    p = classify(ARRIVAL[:-10], "]d1")  # truncated signature
    assert p["type"] == "icao_vds" and not p["valid"]
    p = classify(seal(0x42, 0x42, [(1, c40("ABC"))]))
    assert p["valid"] and "unknown document type" in p["warnings"][0]
    assert p["unknown_features"] == [{"tag": 1, "hex": c40("ABC").hex(), "c40": "ABC"}]
    p = classify(ARRIVAL + b"\x81\x81", "]d1")
    assert p["valid"] and "2 bytes after the signature" in p["warnings"][0]


@pytest.mark.parametrize("payload", [
    b"\xdc\x05" + ARRIVAL[2:],         # unknown version
    b"\xdc\x02" + b"\x00\x00" + ARRIVAL[4:],  # country is not C40
    b"\xdc\x02hello world, not a seal",
    ARRIVAL[:12],
])
def test_not_a_seal(payload):
    assert classify(payload, "]d1")["type"] != "icao_vds"
