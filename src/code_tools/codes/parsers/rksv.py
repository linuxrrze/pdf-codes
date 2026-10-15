"""Austrian cash-register receipt QR code (Registrierkassensicherheitsverordnung, RKSV).

Specification: RKSV (BGBl. II Nr. 410/2015), Anlage "Detailspezifikation", maschinenlesbarer Code,
https://gesetzefinden.at/bundesrecht/verordnungen/rksv

    _<algorithm>-<provider>_<cash register ID>_<receipt number>_<date-time>_<amount 20 %>_<amount 10 %>_
    <amount 13 %>_<amount 0 %>_<amount 19 %>_<encrypted turnover counter>_<certificate serial>_
    <chained value>_<signature>

- Algorithm ``R1``: ES256 signature, AES-256-ICM turnover counter. Provider: the trust service provider of the
  signing certificate (``AT1`` A-Trust, ``AT2`` GLOBALTRUST, ``AT3`` PRIME SIGN; ``AT0`` without one).
- Amounts use a decimal comma. The 19 % rate ("besonderer Steuersatz") applies in Jungholz and Mittelberg.
- The turnover counter is AES-encrypted. Cancelled receipts carry "STO" and training receipts "TRA" in its place.
- The chained value is the start of the SHA-256 of the previous receipt; the signature is base64 of the JWS
  signature, or of "Sicherheitseinrichtung ausgefallen" when the signature device failed.

The signature is not verified: the certificate is not in the code.
"""

from __future__ import annotations

import base64
import binascii
import re

TYPE = "rksv_receipt"
HEADER_RE = re.compile(r"^_R(\d+)-(AT\d+)_")
PROVIDERS = {"AT0": "no trust service provider", "AT1": "A-Trust", "AT2": "GLOBALTRUST", "AT3": "PRIME SIGN"}
RATES = ("standard_20", "reduced_10", "reduced_13", "zero", "special_19")
AMOUNT_RE = re.compile(r"^-?\d+,\d{2}$")
DEVICE_FAILED = "Sicherheitseinrichtung ausgefallen"


def _b64(value: str) -> bytes | None:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def match(data: bytes, aim: str | None = None) -> dict | None:
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    m = HEADER_RE.match(text)
    if not m:
        return None
    parts = text.split("_")[1:]
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [],
                    "algorithm": f"R{m.group(1)}", "provider": m.group(2),
                    "note": "Austrian fiscal receipt (RKSV); signature not verified"}
    if m.group(2) in PROVIDERS:
        result["provider_name"] = PROVIDERS[m.group(2)]
    if len(parts) != 13:
        result["valid"] = False
        result["errors"].append(f"expected 13 fields separated by '_', got {len(parts)}")
        return result

    _, register, receipt, timestamp, *amounts, counter, cert, chain, signature = parts
    result.update({"register_id": register, "receipt_number": receipt, "date_time": timestamp,
                   "certificate_serial": cert, "chained_value": chain})
    if result["algorithm"] != "R1":
        result["warnings"].append(f"unknown algorithm {result['algorithm']}")
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", timestamp):
        result["errors"].append(f"date-time is not YYYY-MM-DDThh:mm:ss: {timestamp!r}")
    gross = {}
    for rate, amount in zip(RATES, amounts):
        if AMOUNT_RE.match(amount):
            gross[rate] = amount.replace(",", ".")
        else:
            result["errors"].append(f"amount for {rate} is not in the format 0,00: {amount!r}")
    result["gross_amounts"] = gross
    if len(gross) == len(RATES):
        cents = sum(int(a.replace(".", "")) for a in gross.values())
        sign, cents = ("-" if cents < 0 else ""), abs(cents)
        result["gross_total"] = f"{sign}{cents // 100}.{cents % 100:02d}"

    decoded_counter = _b64(counter)
    if decoded_counter is None:
        result["errors"].append("turnover counter is not valid base64")
    elif decoded_counter in (b"STO", b"TRA"):
        result["receipt_kind"] = {b"STO": "cancellation", b"TRA": "training"}[decoded_counter]
    else:
        result["receipt_kind"] = "sale"
    if _b64(chain) is None:
        result["errors"].append("chained value is not valid base64")
    decoded_signature = _b64(signature)
    if decoded_signature is None:
        result["errors"].append("signature is not valid base64")
    elif decoded_signature == DEVICE_FAILED.encode():
        result["signature_device_failed"] = True
        result["warnings"].append("signature device failed (Sicherheitseinrichtung ausgefallen)")
    result["signature_verified"] = None
    result["valid"] = not result["errors"]
    return result
