"""DHL return label QR code ("RON|..."), as merchants send it so the customer needs no printer.

DHL does not publish this format. The field meanings were inferred from one label by comparing the fields with
the printed addresses; the two parcel numbers in it are confirmed by their check digits:

- the Identcode (12 digits, DHL parcel number): the first 11 digits weighted alternately 4 and 9, starting with
  4; the check digit tops the sum up to a multiple of 10 (https://www.paketda.de/firmenkunden/paket-pruefziffern.html);
- the Leitcode (14 digits, routing code): recipient postcode (5), street code (3), house number (3), product
  code (2; 33 = return), check digit computed the same way
  (https://www.activebarcode.com/barcode/leitcode/).

Fields separated by "|", ISO 8859-1:

     0 "RON"                    9 sender city            18 (empty)
     1 Identcode               10 sender country         19 (empty)
     2 (empty)                 11 recipient name         20 Leitcode
     3 product ("DHL RETOURE") 12 recipient name 2       21 Identcode again
     4 unknown ("A")           13 recipient street       22 date YYMMDD (31 days after the letter: expiry?)
     5 sender name             14 recipient postcode     23 unknown reference
     6 sender name 2           15 recipient city         24 unknown
     7 sender street           16 recipient country
     8 sender postcode         17 (empty)

The sender is the customer sending the parcel back, the recipient the merchant's return address.
"""

from __future__ import annotations

import re

TYPE = "dhl_return_label"
FIELD_COUNT = 25
LEITCODE_PRODUCTS = {"33": "return"}  # the only code confirmed in a sample; ActiveBarcode lists more
CAVEAT = "inferred from one label by comparison with the printed addresses; not an official decoding"


def dhl_check_digit(digits: str) -> int:
    """Check digit of a DHL Identcode or Leitcode: weights 4, 9, 4, 9, ... modulo 10."""
    total = sum(int(d) * (4 if i % 2 == 0 else 9) for i, d in enumerate(digits))
    return (10 - total % 10) % 10


def _checked(value: str, length: int, what: str, errors: list) -> bool:
    if not re.fullmatch(rf"\d{{{length}}}", value):
        errors.append(f"{what}: expected {length} digits, got {value!r}")
        return False
    if dhl_check_digit(value[:-1]) != int(value[-1]):
        errors.append(f"{what}: check digit mismatch in {value}")
        return False
    return True


def _address(fields: list[str], start: int) -> dict:
    names = ("name", "name2", "street", "postcode", "city", "country")
    return {name: value for name, value in zip(names, fields[start:start + 6]) if value}


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith(b"RON|") or data.count(b"|") < 20:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("iso-8859-1")
    fields = text.split("|")
    fields += [""] * (FIELD_COUNT - len(fields))  # tolerate missing trailing fields; reported below

    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [],
                    "note": "contains the names and addresses of sender and recipient"}
    if len(text.split("|")) != FIELD_COUNT:
        result["warnings"].append(f"{len(text.split('|'))} fields, the known label has {FIELD_COUNT}")

    identcode, leitcode = fields[1], fields[20]
    _checked(identcode, 12, "Identcode", result["errors"])
    if fields[21] and fields[21] != identcode:
        result["warnings"].append("the two Identcode fields differ")
    inferred: dict = {
        "identcode": identcode,
        "product": fields[3] or None,
        "sender": _address(fields, 5),
        "recipient": _address(fields, 11),
    }
    if _checked(leitcode, 14, "Leitcode", result["errors"]):
        inferred["leitcode"] = {
            "code": leitcode, "postcode": leitcode[:5], "street_code": leitcode[5:8],
            "house_number": int(leitcode[8:11]), "product_code": leitcode[11:13],
            "product": LEITCODE_PRODUCTS.get(leitcode[11:13]),
        }
        if inferred["recipient"].get("postcode") not in (None, leitcode[:5]):
            result["warnings"].append("the Leitcode postcode differs from the recipient postcode")
    date = fields[22]
    if re.fullmatch(r"\d{6}", date):
        inferred["date"] = f"20{date[:2]}-{date[2:4]}-{date[4:]}"
    elif date:
        result["warnings"].append(f"field 22: expected a YYMMDD date, got {date!r}")
    unknown = {str(i): fields[i] for i in (4, 23, 24) if fields[i]}
    if unknown:
        inferred["unknown_fields"] = unknown
    inferred["caveat"] = CAVEAT
    result["inferred"] = inferred
    result["valid"] = not result["errors"]
    return result
