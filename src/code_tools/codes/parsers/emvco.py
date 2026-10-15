"""EMVCo merchant-presented QR code (EMV QRCPS-MPM): PIX (Brazil), PromptPay (Thailand), PayNow (Singapore),
QRIS (Indonesia), VietQR, DuitNow, KHQR, Bharat QR and other national instant-payment QR codes.

Specification: EMVCo, "EMV QR Code Specification for Payment Systems: Merchant-Presented Mode", version 1.1,
from emvco.com (free registration).

The payload is a list of data objects ``<ID: 2 digits><length: 2 digits><value>``. It starts with ``000201``
(payload format indicator "01") and ends with ``6304`` + CRC-16/CCITT-FALSE (polynomial 0x1021, initial value
0xFFFF) over everything before the CRC value, in upper-case hex.

- 02-25: card network account numbers; 26-51: templates whose sub-ID 00 is a globally unique identifier (a reverse
  domain name or an AID) naming the payment scheme.
- 52 merchant category code, 53 currency (ISO 4217 numeric), 54 amount, 55-57 tip or convenience fee,
  58 country, 59 merchant name, 60 city, 61 postal code, 62 additional data, 64 merchant name in another language.
"""

from __future__ import annotations

import re

TYPE = "emvco_mpm"
NETWORKS = [((2, 3), "Visa"), ((4, 5), "Mastercard"), ((9, 10), "Discover"), ((11, 12), "American Express"),
            ((13, 14), "JCB"), ((15, 16), "UnionPay")]
SCHEMES = {
    "br.gov.bcb.pix": "PIX (Brazil)",
    "A000000677010111": "PromptPay (Thailand)",
    "A000000677010112": "PromptPay bill payment (Thailand)",
    "SG.PAYNOW": "PayNow (Singapore)",
    "ID.CO.QRIS.WWW": "QRIS (Indonesia)",
    "A000000727": "VietQR / NAPAS (Vietnam)",
}
CURRENCIES = {"036": "AUD", "116": "KHR", "124": "CAD", "156": "CNY", "344": "HKD", "356": "INR", "360": "IDR",
              "392": "JPY", "410": "KRW", "458": "MYR", "484": "MXN", "608": "PHP", "702": "SGD", "704": "VND",
              "756": "CHF", "764": "THB", "826": "GBP", "840": "USD", "978": "EUR", "986": "BRL"}
TOP_LEVEL = {"52": "merchant_category_code", "54": "amount", "56": "convenience_fee_fixed",
             "57": "convenience_fee_percentage", "58": "country", "59": "merchant_name", "60": "merchant_city",
             "61": "postal_code"}
ADDITIONAL = {"01": "bill_number", "02": "mobile_number", "03": "store_label", "04": "loyalty_number",
              "05": "reference_label", "06": "customer_label", "07": "terminal_label",
              "08": "purpose_of_transaction", "09": "additional_consumer_data_request"}
LANGUAGE = {"00": "language", "01": "merchant_name", "02": "merchant_city"}
TIP = {"01": "consumer enters tip", "02": "fixed convenience fee", "03": "percentage convenience fee"}


def crc16(data: bytes) -> str:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def parse_tlv(text: str) -> list[tuple[str, str]] | None:
    """Split ID-length-value objects; None if they do not tile the text exactly."""
    out, pos = [], 0
    while pos < len(text):
        head = text[pos:pos + 4]
        if not re.fullmatch(r"\d{4}", head):
            return None
        n = int(head[2:])
        value = text[pos + 4:pos + 4 + n]
        if len(value) != n:
            return None
        out.append((head[:2], value))
        pos += 4 + n
    return out


def _named(value: str, names: dict[str, str]) -> dict:
    out: dict = {}
    for sub, v in parse_tlv(value) or []:
        out[names.get(sub, f"id_{sub}")] = v
    return out


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith(b"000201") or (aim is not None and aim in ("]Q3", "]d2", "]C1")):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    objects = parse_tlv(text)
    if objects is None or len(objects) < 3:
        return None

    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "accounts": []}
    ids = [i for i, _ in objects]
    if ids[-1] != "63":
        result["errors"].append("the CRC (ID 63) must be the last data object")
    else:
        expected = crc16(text[:-4].encode("utf-8"))
        if objects[-1][1].upper() != expected:
            result["errors"].append(f"CRC is {objects[-1][1]}, expected {expected}")
    if len(set(ids)) != len(ids):
        result["warnings"].append("a data object ID occurs more than once")

    for i, value in objects:
        n = int(i)
        if i == "01":
            result["initiation"] = {"11": "static", "12": "dynamic"}.get(value, value)
        elif 2 <= n <= 25:
            network = next((name for ids_, name in NETWORKS if n in ids_), "EMVCo reserved")
            result["accounts"].append({"id": i, "network": network, "value": value})
        elif 26 <= n <= 51:
            sub = dict(parse_tlv(value) or [])
            entry: dict = {"id": i, "fields": sub}
            gui = sub.get("00")
            if gui:
                entry["identifier"] = gui
                scheme = SCHEMES.get(gui) or SCHEMES.get(gui.lower()) or SCHEMES.get(gui.upper())
                if scheme:
                    entry["scheme"] = scheme
            result["accounts"].append(entry)
        elif i == "53":
            result["currency"] = CURRENCIES.get(value, value)
        elif i == "55":
            result["tip"] = TIP.get(value, value)
        elif i in TOP_LEVEL:
            result[TOP_LEVEL[i]] = value
        elif i == "62":
            result["additional_data"] = _named(value, ADDITIONAL)
        elif i == "64":
            result["alternate_language"] = _named(value, LANGUAGE)
        elif i not in ("00", "63"):
            result.setdefault("other", {})[i] = value

    if "amount" in result and not re.fullmatch(r"\d+(\.\d+)?", result["amount"]):
        result["errors"].append(f"malformed amount {result['amount']!r}")
    for required in ("merchant_category_code", "currency", "country", "merchant_name", "merchant_city"):
        if required not in result:
            result["warnings"].append(f"mandatory field {required} missing")
    if not result["accounts"]:
        result["errors"].append("no merchant account information (IDs 02-51)")
    result["valid"] = not result["errors"]
    return result
