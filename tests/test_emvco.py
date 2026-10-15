"""EMVCo merchant-presented QR codes. PIX is the widely published example of the Banco Central do Brasil
(fictitious merchant "Fulano de Tal"); the other codes are invented."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers.emvco import crc16

PIX = (b"00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
       b"5913Fulano de Tal6008BRASILIA62070503***63041D3D")


def tlv(i: str, value: str) -> str:
    return f"{i}{len(value):02d}{value}"


def code(*objects: str) -> bytes:
    body = "".join(objects) + "6304"
    return (body + crc16(body.encode())).encode()


def test_pix_example():
    p = classify(PIX, "]Q1")
    assert p["type"] == "emvco_mpm" and p["valid"] and p["warnings"] == [], p["errors"]
    assert p["accounts"][0]["scheme"] == "PIX (Brazil)"
    assert p["accounts"][0]["fields"]["01"] == "123e4567-e12b-12d1-a456-426655440000"
    assert (p["currency"], p["country"], p["merchant_name"], p["merchant_city"]) == ("BRL", "BR", "Fulano de Tal",
                                                                                     "BRASILIA")
    assert p["additional_data"] == {"reference_label": "***"}


def test_dynamic_code_with_card_network_and_language():
    p = classify(code(tlv("00", "01"), tlv("01", "12"), tlv("02", "4000123412341234"),
                      tlv("29", tlv("00", "A000000677010111") + tlv("01", "0066812345678")),
                      tlv("52", "5812"), tlv("53", "764"), tlv("54", "120.50"), tlv("58", "TH"),
                      tlv("59", "Somchai Shop"), tlv("60", "Bangkok"),
                      tlv("64", tlv("00", "TH") + tlv("01", "ร้านสมชาย"))))
    assert p["valid"] and p["warnings"] == [], p["errors"]
    assert p["initiation"] == "dynamic" and p["amount"] == "120.50" and p["currency"] == "THB"
    assert p["accounts"][0] == {"id": "02", "network": "Visa", "value": "4000123412341234"}
    assert p["accounts"][1]["scheme"] == "PromptPay (Thailand)"
    assert p["alternate_language"] == {"language": "TH", "merchant_name": "ร้านสมชาย"}


def test_problems():
    p = classify(PIX[:-4] + b"0000")
    assert p["type"] == "emvco_mpm" and not p["valid"] and "expected 1D3D" in p["errors"][0]
    p = classify(code(tlv("00", "01"), tlv("26", tlv("00", "br.gov.bcb.pix")), tlv("54", "12,50")))
    assert not p["valid"] and "amount" in p["errors"][0]
    assert any("merchant_name" in w for w in p["warnings"])


@pytest.mark.parametrize("payload, aim", [
    (b"000201", "]Q1"),
    (b"0002012345", "]Q1"),            # objects do not tile the text
    (PIX, "]Q3"),                      # GS1 QR: AI 00 (SSCC)
    (b"00020126580014br.gov.bcb.pix0136123e", "]Q1"),
])
def test_not_emvco(payload, aim):
    assert classify(payload, aim)["type"] != "emvco_mpm"
