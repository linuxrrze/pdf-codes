"""Austrian RKSV receipt QR codes. Register IDs, numbers and signatures are invented."""

from __future__ import annotations

import base64

import pytest

from code_tools.codes.classify import classify


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def receipt(provider="AT1", amounts=("12,50", "3,20", "0,00", "0,00", "0,00"), counter=b64(b"\x01" * 8),
            signature=b64(b"\x02" * 64), timestamp="2026-10-15T09:41:07") -> bytes:
    fields = ["", f"R1-{provider}", "KASSE-01", "4711", timestamp, *amounts, counter, "1a2b3c4d",
              b64(b"\x03" * 8), signature]
    return "_".join(fields).encode()


def test_receipt():
    p = classify(receipt(), "]Q1")
    assert p["type"] == "rksv_receipt" and p["valid"] and p["warnings"] == [], p["errors"]
    assert (p["algorithm"], p["provider"], p["provider_name"]) == ("R1", "AT1", "A-Trust")
    assert (p["register_id"], p["receipt_number"], p["date_time"]) == ("KASSE-01", "4711", "2026-10-15T09:41:07")
    assert p["gross_amounts"] == {"standard_20": "12.50", "reduced_10": "3.20", "reduced_13": "0.00", "zero": "0.00",
                                  "special_19": "0.00"}
    assert p["gross_total"] == "15.70" and p["receipt_kind"] == "sale"


def test_special_receipts():
    assert classify(receipt(counter=b64(b"STO")))["receipt_kind"] == "cancellation"
    assert classify(receipt(counter=b64(b"TRA")))["receipt_kind"] == "training"
    p = classify(receipt(signature=b64(b"Sicherheitseinrichtung ausgefallen")))
    assert p["valid"] and p["signature_device_failed"] and "ausgefallen" in p["warnings"][0]
    p = classify(receipt(amounts=("-12,50", "0,00", "0,00", "0,00", "0,00")))
    assert p["gross_total"] == "-12.50"


def test_problems():
    p = classify(receipt(amounts=("12.50", "0,00", "0,00", "0,00", "0,00")))
    assert not p["valid"] and "standard_20" in p["errors"][0]
    p = classify(receipt(counter="not base64!"))
    assert not p["valid"] and "turnover counter" in p["errors"][0]
    p = classify(receipt(timestamp="15.10.2026 09:41"))
    assert not p["valid"] and "date-time" in p["errors"][0]
    p = classify(b"_R1-AT1_KASSE_4711")
    assert p["type"] == "rksv_receipt" and not p["valid"] and "13 fields" in p["errors"][0]
    assert classify(receipt(provider="AT9"))["valid"]


@pytest.mark.parametrize("payload", [b"R1-AT1_KASSE", b"_R1-ATX_KASSE", b"V0;_R1-AT1_", b"text _R1-AT1_x"])
def test_not_rksv(payload):
    assert classify(payload, "]Q1")["type"] != "rksv_receipt"
