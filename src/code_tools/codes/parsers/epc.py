"""EPC QR code ("GiroCode"), EPC069-12: SEPA credit transfer data.

Layout, one field per line:
    BCD / version 001|002 / charset 1-8 / SCT|INST / BIC / name / IBAN / amount EURx.yy /
    purpose / structured reference / unstructured text / beneficiary-to-originator info
Trailing empty fields may be omitted. Version 001 requires the BIC.
"""

from __future__ import annotations

import re

from .common import BIC_RE, decode_text, iban_valid, rf_reference_valid, split_lines

TYPE = "epc"
CHARSETS = {"1": "utf-8", "2": "iso-8859-1", "3": "iso-8859-2", "4": "iso-8859-4", "5": "iso-8859-5",
            "6": "iso-8859-7", "7": "iso-8859-10", "8": "iso-8859-15"}
# The standard requires a decimal point, but codes with a decimal comma ("EUR482,57") are common in the
# wild and German banking apps accept them, so a comma is accepted with a warning.
AMOUNT_RE = re.compile(r"^EUR(\d{1,9})(?:([.,])(\d{1,2}))?$")
FIELDS = ("service_tag", "version", "charset", "identification", "bic", "name", "iban", "amount_raw",
          "purpose", "reference", "text", "information")


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith((b"BCD\n", b"BCD\r\n")):
        return None
    # The charset field decides the encoding; peek at it with ASCII before decoding the rest.
    head = split_lines(data[:16].decode("ascii", "replace"))
    charset = head[2].strip() if len(head) > 2 else "1"
    text = decode_text(data, CHARSETS.get(charset, "utf-8")) or data.decode("utf-8", "replace")
    lines = split_lines(text)
    while lines and lines[-1] == "" and len(lines) > len(FIELDS):
        lines.pop()

    errors: list[str] = []
    warnings: list[str] = []
    if len(lines) > len(FIELDS):
        errors.append(f"{len(lines)} lines, at most {len(FIELDS)} allowed")
    values = dict(zip(FIELDS, [line.strip() for line in lines] + [""] * (len(FIELDS) - len(lines))))

    if values["version"] not in ("001", "002"):
        errors.append(f"unknown version {values['version']!r}")
    if values["charset"] not in CHARSETS:
        errors.append(f"unknown character set {values['charset']!r}")
    if values["identification"] not in ("SCT", "INST"):
        errors.append(f"identification must be SCT or INST, not {values['identification']!r}")
    if values["bic"]:
        if not BIC_RE.match(values["bic"]):
            errors.append(f"malformed BIC {values['bic']!r}")
    elif values["version"] == "001":
        errors.append("BIC is required in version 001")
    if not values["name"]:
        errors.append("beneficiary name missing")
    elif len(values["name"]) > 70:
        errors.append("beneficiary name longer than 70 characters")
    if not iban_valid(values["iban"]):
        errors.append(f"invalid IBAN {values['iban']!r}")

    amount = None
    if values["amount_raw"]:
        m = AMOUNT_RE.match(values["amount_raw"])
        if not m:
            errors.append(f"malformed amount {values['amount_raw']!r}")
        else:
            amount = f"{int(m.group(1))}.{(m.group(3) or '0').ljust(2, '0')}"
            if m.group(2) == ",":
                warnings.append(f"amount {values['amount_raw']!r} uses a decimal comma; "
                                "the standard requires a point")
            if not 0.01 <= float(amount) <= 999999999.99:
                errors.append("amount out of range")
    if values["purpose"] and not re.fullmatch(r"[A-Z0-9]{4}", values["purpose"]):
        errors.append(f"malformed purpose code {values['purpose']!r}")
    if values["reference"] and values["text"]:
        errors.append("structured reference and unstructured text are mutually exclusive")
    if values["reference"].upper().startswith("RF") and not rf_reference_valid(values["reference"]):
        errors.append(f"invalid RF creditor reference {values['reference']!r}")
    if len(data) > 331:
        errors.append(f"payload is {len(data)} bytes, at most 331 allowed")

    return {
        "type": TYPE,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "version": values["version"],
        "identification": values["identification"] or None,
        "bic": values["bic"] or None,
        "name": values["name"] or None,
        "iban": values["iban"].replace(" ", "") or None,
        "amount": amount,
        "currency": "EUR" if amount else None,
        "purpose": values["purpose"] or None,
        "reference": values["reference"] or None,
        "text": values["text"] or None,
        "information": values["information"] or None,
    }
