"""German cash-register receipt QR code (KassenSichV / TSE), DSFinV-K Anhang I.

Specification: Bundeszentralamt für Steuern, DSFinV-K version 2.4, Anhang I "Definition 'Art' und 'Daten' des
Vorgangs; QR-Code", https://www.bzst.de/DE/Unternehmen/Aussenpruefungen/DigitaleSchnittstelleFinV/
digitaleschnittstellefinv_node.html

    V0;<kassen-seriennummer>;<processType>;<processData>;<transaktions-nummer>;<signatur-zaehler>;
    <start-zeit>;<log-time>;<sig-alg>;<log-time-format>;<signatur>;<public-key>

processData of "Kassenbeleg-V1": <Vorgangstyp>^<gross sales per VAT rate>^<payments>, with the gross sales in
the order: standard rate, reduced rate, average rate §24(1)Nr.3 UStG, average rate §24(1)Nr.1 UStG, 0 %; and
payments as <amount>:<Bar|Unbar>[:<ISO 4217 currency, only if not EUR>] joined by "_".
processData of "Bestellung-V1" is CSV (quantity;"description";price) with CR line breaks, so it may itself
contain ";": the twelve fields are therefore split from both ends.

The TSE signature is not verified. The TSE serial number is the SHA-256 of the public key (Anhang I).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from decimal import Decimal

TYPE = "kassensichv_receipt"
VAT_RATES = ("standard", "reduced", "average_24_1_3", "average_24_1_1", "zero")
AMOUNT_RE = re.compile(r"^-?\d+\.\d{2}$")
PAYMENT_RE = re.compile(r"^(-?\d+\.\d{2}):(Bar|Unbar)(?::([A-Z]{3}))?$")


def _kassenbeleg(data: str, result: dict) -> dict:
    parts = data.split("^")
    if len(parts) != 3:
        result["errors"].append("Kassenbeleg-V1 processData needs three parts separated by '^'")
        return {}
    kind, sales_raw, payments_raw = parts
    sales_list = sales_raw.split("_")
    if len(sales_list) != 5 or not all(AMOUNT_RE.match(a) for a in sales_list):
        result["errors"].append(f"gross sales must be five amounts with two decimals, got {sales_raw!r}")
        sales = {}
    else:
        sales = dict(zip(VAT_RATES, sales_list))
    payments = []
    for item in filter(None, payments_raw.split("_")):
        m = PAYMENT_RE.match(item)
        if not m:
            result["errors"].append(f"malformed payment {item!r}")
            continue
        payments.append({"amount": m.group(1), "type": m.group(2), "currency": m.group(3) or "EUR"})
    if sales and payments and all(p["currency"] == "EUR" for p in payments):
        total = sum(Decimal(a) for a in sales.values())
        paid = sum(Decimal(p["amount"]) for p in payments)
        if total != paid:
            result["warnings"].append(f"gross sales {total} differ from payments {paid}")
    return {"transaction_type": kind, "gross_sales": sales,
            "gross_total": str(sum(Decimal(a) for a in sales.values())) if sales else None, "payments": payments}


def _bestellung(data: str) -> dict:
    items = []
    for line in filter(None, data.split("\r")):
        m = re.match(r'^([^;]*);"((?:[^"]|"")*)";([^;]*)$', line)
        if m:
            items.append({"quantity": m.group(1), "description": m.group(2).replace('""', '"'),
                          "price": m.group(3)})
        else:
            items.append({"raw": line})
    return {"items": items}


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith(b"V0;"):
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parts = text.split(";")
    if len(parts) < 12:
        return None
    head, tail = parts[:3], parts[-8:]
    process_data = ";".join(parts[3:-8])
    _, register, process_type = head
    tx, counter, start, log_time, sig_alg, time_format, signature, public_key = tail

    result: dict = {
        "type": TYPE, "valid": True, "errors": [], "warnings": [],
        "register_serial": register, "process_type": process_type,
        "transaction_number": tx, "signature_counter": counter,
        "start_time": start, "log_time": log_time,
        "signature_algorithm": sig_alg, "log_time_format": time_format,
        "signature": signature, "public_key": public_key,
        "signature_verified": None,
        "note": "German fiscal receipt (KassenSichV); TSE signature not verified",
    }
    for name, value in (("transaction_number", tx), ("signature_counter", counter)):
        if not value.isdigit():
            result["errors"].append(f"{name} must be numeric, got {value!r}")
    for name, value in (("start_time", start), ("log_time", log_time)):
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z?", value):
            result["warnings"].append(f"{name} is not in the format YYYY-MM-DDThh:mm:ss.fffZ: {value!r}")
    try:
        key = base64.b64decode(public_key, validate=True)
        result["tse_serial"] = hashlib.sha256(key).hexdigest()
    except (binascii.Error, ValueError):
        result["errors"].append("public key is not valid base64")

    if process_type == "Kassenbeleg-V1":
        result["receipt"] = _kassenbeleg(process_data, result)
    elif process_type == "Bestellung-V1":
        result["order"] = _bestellung(process_data)
    else:
        result["process_data"] = process_data
        if process_type != "SonstigerVorgang":
            result["warnings"].append(f"unknown processType {process_type!r}")
    result["valid"] = not result["errors"]
    return result
