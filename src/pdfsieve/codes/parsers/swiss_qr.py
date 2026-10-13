"""Swiss QR-bill (SIX Implementation Guidelines 2.x): payment part QR code.

Fixed layout of at least 31 lines: header (SPC / 0200 / 1), account, creditor (7 lines), ultimate creditor
(7 lines, reserved, must be empty), amount, currency, ultimate debtor (7 lines), reference type and reference,
unstructured message, trailer EPD, then optional billing information and up to two alternative procedures.
"""

from __future__ import annotations

import re

from .common import decode_text, iban_valid, rf_reference_valid, split_lines

TYPE = "swiss_qr"
MIN_LINES = 31
MAX_LINES = 34
AMOUNT_RE = re.compile(r"^\d{1,9}\.\d{2}$")


def _address(lines: list[str]) -> dict | None:
    kind, name, line1, line2, postcode, town, country = lines
    if not any(lines):
        return None
    if kind == "S":
        return {"address_type": "structured", "name": name, "street": line1 or None, "building": line2 or None,
                "postcode": postcode or None, "town": town or None, "country": country or None}
    return {"address_type": "combined" if kind == "K" else kind or None, "name": name,
            "address_line_1": line1 or None, "address_line_2": line2 or None, "country": country or None}


def _address_errors(label: str, lines: list[str], required: bool) -> list[str]:
    kind, name, *_rest, country = lines
    if not any(lines):
        return [f"{label} missing"] if required else []
    errors = []
    if kind not in ("S", "K"):
        errors.append(f"{label}: address type must be S or K, not {kind!r}")
    if not name:
        errors.append(f"{label}: name missing")
    if not re.fullmatch(r"[A-Z]{2}", country):
        errors.append(f"{label}: country must be a two-letter code, not {country!r}")
    return errors


def qr_reference_valid(ref: str) -> bool:
    """27-digit QR reference with recursive mod-10 check digit."""
    if not re.fullmatch(r"\d{27}", ref):
        return False
    table = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)
    carry = 0
    for digit in ref[:-1]:
        carry = table[(carry + int(digit)) % 10]
    return (10 - carry) % 10 == int(ref[-1])


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith((b"SPC\n", b"SPC\r\n")):
        return None
    text = decode_text(data) or data.decode("utf-8", "replace")
    lines = [line.strip() for line in split_lines(text)]
    while len(lines) > MIN_LINES and lines[-1] == "":
        lines.pop()
    errors: list[str] = []
    if len(lines) < MIN_LINES:
        errors.append(f"{len(lines)} lines, at least {MIN_LINES} required")
        lines += [""] * (MIN_LINES - len(lines))
    if len(lines) > MAX_LINES:
        errors.append(f"{len(lines)} lines, at most {MAX_LINES} allowed")

    version, coding, iban = lines[1], lines[2], lines[3].replace(" ", "")
    creditor, ultimate_creditor = lines[4:11], lines[11:18]
    amount, currency = lines[18], lines[19]
    debtor = lines[20:27]
    ref_type, reference, message, trailer = lines[27], lines[28], lines[29], lines[30]
    billing = lines[31] if len(lines) > 31 else ""
    alternatives = [x for x in lines[32:34] if x]

    if not re.fullmatch(r"02\d\d", version):
        errors.append(f"unsupported version {version!r}")
    if coding != "1":
        errors.append(f"coding type must be 1, not {coding!r}")
    if iban[:2] not in ("CH", "LI") or not iban_valid(iban):
        errors.append(f"invalid CH/LI IBAN {iban!r}")
    # A QR-IBAN has an institution ID (positions 5-9) in the range 30000-31999.
    qr_iban = iban_valid(iban) and iban[4:9].isdigit() and 30000 <= int(iban[4:9]) <= 31999
    errors += _address_errors("creditor", creditor, required=True)
    if any(ultimate_creditor):
        errors.append("ultimate creditor fields are reserved and must be empty")
    if amount and not AMOUNT_RE.match(amount):
        errors.append(f"malformed amount {amount!r}")
    if currency not in ("CHF", "EUR"):
        errors.append(f"currency must be CHF or EUR, not {currency!r}")
    errors += _address_errors("debtor", debtor, required=False)

    if ref_type == "QRR":
        if not qr_iban:
            errors.append("QRR reference requires a QR-IBAN")
        if not qr_reference_valid(reference):
            errors.append(f"invalid QR reference {reference!r}")
    elif ref_type == "SCOR":
        if qr_iban:
            errors.append("a QR-IBAN requires a QRR reference")
        if not rf_reference_valid(reference):
            errors.append(f"invalid creditor reference {reference!r}")
    elif ref_type == "NON":
        if qr_iban:
            errors.append("a QR-IBAN requires a QRR reference")
        if reference:
            errors.append("reference must be empty for reference type NON")
    else:
        errors.append(f"reference type must be QRR, SCOR or NON, not {ref_type!r}")
    if trailer != "EPD":
        errors.append(f"trailer must be EPD, not {trailer!r}")
    if len(message) > 140:
        errors.append("message longer than 140 characters")

    return {
        "type": TYPE,
        "valid": not errors,
        "errors": errors,
        "version": version,
        "iban": iban or None,
        "qr_iban": qr_iban,
        "creditor": _address(creditor),
        "amount": amount or None,
        "currency": currency or None,
        "debtor": _address(debtor),
        "reference_type": ref_type or None,
        "reference": reference or None,
        "message": message or None,
        "billing_information": billing or None,
        "alternative_procedures": alternatives,
    }
