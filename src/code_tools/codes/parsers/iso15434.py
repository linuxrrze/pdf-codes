"""ISO/IEC 15434 envelopes ("[)>"), with ANSI MH10.8.2 data identifiers, e.g. IFA PPN codes on German medicine
packs (securPharm), electronic component labels and UPS MaxiCode.

Specifications:
- ISO/IEC 15434 (syntax; not freely available): ``[)>`` RS, then one or more envelopes
  ``<format> GS <field> GS <field> ... RS``, then EOT. A DataMatrix "Macro 05/06" codeword stands for the
  header and trailer; the decoder expands it.
- ANSI MH10.8.2 data identifiers (format 06), a free download from MHI.
- IFA "Spezifikation für die Codierung von Verifikationsmerkmalen in Data Matrix Codes" (securPharm, format 06):
  9N PPN, 1T batch, D expiry date (YYMMDD, day 00 = end of month), S serial number, 8P optional GTIN/NTIN.
- PPN: 2-character product registration agency code ("11" = IFA, then the 8-digit PZN) + product number + 2 check
  digits: the sum of each character's ASCII value times its position starting at 2, modulo 97.
- PZN (8 digits): the first seven digits times 1 to 7, summed, modulo 11, is the last digit (10 is not allowed).

Format 05 (GS1 application identifiers) is split with the GS1 parser. Other formats are listed field by field.
"""

from __future__ import annotations

import re

from . import gs1

TYPE = "iso15434"
HEADER = "[)>\x1e"
RS, GS, EOT = "\x1e", "\x1d", "\x04"
DI_RE = re.compile(r"^(\d{0,3}[A-Z])(.*)$", re.DOTALL)
DI_NAMES = {
    "P": "customer part number", "1P": "supplier part number", "8P": "GTIN", "Q": "quantity",
    "S": "serial number", "1T": "batch/lot", "D": "date (YYMMDD)", "14D": "expiry date (YYYYMMDD)",
    "16D": "production date (YYYYMMDD)", "9N": "PPN", "K": "order number (customer)",
    "1K": "order number (supplier)", "4L": "country of origin", "10D": "date code (YYWW)",
}
FORMATS = {"01": "transportation (ANSI MH10.8.3)", "02": "complete EDI message", "05": "GS1 application identifiers",
           "06": "ANSI MH10.8.2 data identifiers", "07": "free text", "12": "text element identifiers"}


def ppn_check(ppn: str) -> str:
    return f"{sum(ord(c) * i for i, c in enumerate(ppn[:-2], 2)) % 97:02d}"


def pzn_valid(pzn: str) -> bool:
    if not re.fullmatch(r"\d{8}", pzn):
        return False
    check = sum(int(d) * i for i, d in enumerate(pzn[:7], 1)) % 11
    return check != 10 and check == int(pzn[7])


def _yymmdd(value: str) -> str | None:
    m = re.fullmatch(r"(\d\d)(0[1-9]|1[0-2])(\d\d)", value)
    if not m or int(m.group(3)) > 31:
        return None
    yy, mm, dd = m.groups()
    return f"20{yy}-{mm}" if dd == "00" else f"20{yy}-{mm}-{dd}"


def _format06(fields: list[str], result: dict) -> list[dict]:
    elements = []
    for field in fields:
        m = DI_RE.match(field)
        if not m:
            result["errors"].append(f"field without a data identifier: {field!r}")
            continue
        di, value = m.groups()
        entry = {"di": di, "value": value}
        if di in DI_NAMES:
            entry["name"] = DI_NAMES[di]
        elements.append(entry)
    by_di = {e["di"]: e["value"] for e in elements}
    if "9N" in by_di:
        result["pharma"] = _pharma(by_di, result)
    return elements


def _pharma(by_di: dict[str, str], result: dict) -> dict:
    ppn = by_di["9N"]
    pharma: dict = {"ppn": ppn}
    if not re.fullmatch(r"[0-9A-Z]{2}[0-9A-Z]{1,18}\d{2}", ppn):
        result["errors"].append(f"malformed PPN {ppn!r}")
    elif ppn_check(ppn) != ppn[-2:]:
        result["errors"].append(f"PPN check digits wrong: {ppn[-2:]}, expected {ppn_check(ppn)}")
    if ppn.startswith("11") and len(ppn) == 12:
        pharma["pzn"] = ppn[2:10]
        if not pzn_valid(pharma["pzn"]):
            result["errors"].append(f"PZN check digit wrong in {pharma['pzn']}")
    if "1T" in by_di:
        pharma["batch"] = by_di["1T"]
    if "D" in by_di:
        pharma["expiry"] = _yymmdd(by_di["D"])
        if pharma["expiry"] is None:
            result["errors"].append(f"expiry date is not YYMMDD: {by_di['D']!r}")
    if "S" in by_di:
        pharma["serial"] = by_di["S"]
    if "8P" in by_di:
        pharma["gtin"] = by_di["8P"]
        if not gs1.check_digit_ok(by_di["8P"]):
            result["errors"].append(f"GTIN check digit wrong in {by_di['8P']}")
    missing = [name for di, name in (("1T", "batch"), ("D", "expiry"), ("S", "serial")) if di not in by_di]
    if missing:
        result["warnings"].append(f"securPharm codes also carry {', '.join(missing)}")
    return pharma


def match(data: bytes, aim: str | None = None) -> dict | None:
    try:
        text = data.decode("latin-1")
    except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes every byte
        return None
    if not text.startswith(HEADER):
        return None
    body = text[len(HEADER):]
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "envelopes": []}
    if body.endswith(EOT):
        body = body[:-1]
    else:
        result["warnings"].append("no end-of-transmission (EOT) trailer")
    for raw in filter(None, body.split(RS)):
        fmt, _, rest = raw.partition(GS)
        envelope: dict = {"format": fmt}
        if fmt in FORMATS:
            envelope["format_name"] = FORMATS[fmt]
        else:
            result["warnings"].append(f"unknown format {fmt!r}")
        fields = rest.split(GS) if rest else []
        if fmt == "06":
            envelope["elements"] = _format06([f for f in fields if f], result)
        elif fmt == "05":
            elements, errors = gs1._parse_raw(rest)
            result["errors"].extend(errors)
            envelope["elements"] = [gs1._describe(ai, value, result["errors"]) for ai, value in elements]
        else:
            envelope["fields"] = fields
        result["envelopes"].append(envelope)
    if not result["envelopes"]:
        result["errors"].append("no envelope after the [)> header")
    result["valid"] = not result["errors"]
    return result
