"""GS1 element strings (GS1-128, GS1 DataMatrix, GS1 QR, GS1 DataBar, GS1 DotCode).

Recognised by the AIM symbology identifier that marks FNC1-in-first-position (]C1 ]d2 ]Q3 ]e0 ]J1), by such an
identifier at the start of the payload, or by the human-readable "(01)...(17)..." form.

EAN-13, EAN-8, UPC-A and UPC-E (AIM ]E0, ]E4, ]E3 with add-on) carry a single GTIN and are reported as AI 01.
A GTIN-13 in prefix 977, 978 or 979 is a publication number (GS1 General Specifications 1.4.4 and 1.4.5;
ISBN Users' Manual, ISSN Manual, ISMN Users' Manual):
- 978 and 979-1...979-9: ISBN-13; 978 also has an ISBN-10 (the nine digits after 978 + mod 11 check, X = 10).
- 979-0: ISMN (printed music).
- 977: ISSN, the seven digits after 977 + mod 11 check (X = 10), then a two-digit variant ("price code").
The two- or five-digit EAN add-on (issue number of a periodical, price of a book) is passed through.
"""

from __future__ import annotations

import re

TYPE = "gs1"
GS1_AIM = ("]C1", "]d2", "]Q3", "]e0", "]J1")
EAN_AIM = ("]E0", "]E3", "]E4")
EAN_RE = re.compile(r"^(\d{13}|\d{12}|\d{8}) ?(\d{2}|\d{5})?$")
GS = "\x1d"

# Data length (excluding the AI) for AIs whose length is fixed, keyed by the first two digits.
FIXED_LENGTH = {"00": 18, "01": 14, "02": 14, "03": 14, "04": 16, "11": 6, "12": 6, "13": 6, "14": 6, "15": 6,
                "16": 6, "17": 6, "18": 6, "19": 6, "20": 2, "31": 6, "32": 6, "33": 6, "34": 6, "35": 6, "36": 6,
                "41": 13}
THREE_DIGIT = {"23", "24", "25", "40", "41", "42"}
FOUR_DIGIT = {"31", "32", "33", "34", "35", "36", "39", "43", "70", "71", "72", "80", "81", "82"}
NAMES = {
    "00": "SSCC", "01": "GTIN", "02": "CONTENT", "10": "BATCH/LOT", "11": "PROD DATE", "12": "DUE DATE",
    "13": "PACK DATE", "15": "BEST BEFORE", "16": "SELL BY", "17": "USE BY", "20": "VARIANT", "21": "SERIAL",
    "22": "CPV", "240": "ADDITIONAL ID", "241": "CUST. PART No.", "250": "SECONDARY SERIAL", "30": "VAR. COUNT",
    "37": "COUNT", "400": "ORDER NUMBER", "401": "GINC", "402": "GSIN", "403": "ROUTE", "410": "SHIP TO LOC",
    "411": "BILL TO", "412": "PURCHASE FROM", "413": "SHIP FOR LOC", "414": "LOC No.", "415": "PAY TO",
    "416": "PROD/SERV LOC", "420": "SHIP TO POST", "421": "SHIP TO POST", "422": "ORIGIN", "7003": "EXPIRY TIME",
    "8004": "GIAI", "8020": "REF No.", "8200": "PRODUCT URL",
}
MEASURES = {"310": "NET WEIGHT (kg)", "320": "NET WEIGHT (lb)", "311": "LENGTH (m)", "330": "GROSS WEIGHT (kg)",
            "392": "PRICE", "393": "PRICE (ISO)"}
DATE_AIS = {"11", "12", "13", "15", "16", "17"}
CHECK_DIGIT_AIS = {"00", "01", "02", "410", "411", "412", "413", "414", "415", "416"}
HRI_RE = re.compile(r"\((\d{2,4})\)([^()]*)")


def _ai_length(digits: str) -> int:
    prefix = digits[:2]
    if prefix in FOUR_DIGIT:
        return 4
    if prefix in THREE_DIGIT:
        return 3
    return 2


def check_digit_ok(number: str) -> bool:
    if not number.isdigit() or len(number) < 2:
        return False
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(number[:-1])))
    return (10 - total % 10) % 10 == int(number[-1])


def _mod11_check(digits: str) -> str:
    """ISBN-10 / ISSN check character: weights from len+1 down to 2, mod 11, 10 written as X."""
    total = sum(int(d) * w for d, w in zip(digits, range(len(digits) + 1, 1, -1)))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def publication(gtin: str) -> dict | None:
    """ISBN, ISMN or ISSN encoded in a GTIN-13 (or a GTIN-14 with indicator 0)."""
    if len(gtin) == 14 and gtin[0] == "0":
        gtin = gtin[1:]
    if len(gtin) != 13:
        return None
    if gtin.startswith("9790"):
        return {"ismn": gtin}
    if gtin.startswith(("978", "979")):
        out = {"isbn13": gtin}
        if gtin.startswith("978"):
            out["isbn10"] = gtin[3:12] + _mod11_check(gtin[3:12])
        return out
    if gtin.startswith("977"):
        issn = gtin[3:10] + _mod11_check(gtin[3:10])
        return {"issn": f"{issn[:4]}-{issn[4:]}", "variant": gtin[10:12]}
    return None


def upc_e_to_a(code: str) -> str:
    """Expand an 8-digit UPC-E (number system, six digits, check digit) to UPC-A."""
    s, d, check = code[0], code[1:7], code[7]
    if d[5] in "012":
        body = d[:2] + d[5] + "0000" + d[2:5]
    elif d[5] == "3":
        body = d[:3] + "00000" + d[3:5]
    elif d[5] == "4":
        body = d[:4] + "00000" + d[4]
    else:
        body = d[:5] + "0000" + d[5]
    return s + body + check


def _parse_raw(data: str) -> tuple[list[tuple[str, str]], list[str]]:
    elements, errors = [], []
    pos = 0
    while pos < len(data):
        if data[pos] == GS:
            pos += 1
            continue
        ai_len = _ai_length(data[pos:pos + 2])
        ai = data[pos:pos + ai_len]
        if len(ai) != ai_len or not ai.isdigit():
            errors.append(f"expected an application identifier at offset {pos}")
            break
        pos += ai_len
        fixed = FIXED_LENGTH.get(ai[:2])
        if fixed is not None:
            value = data[pos:pos + fixed]
            if len(value) != fixed:
                errors.append(f"AI {ai}: expected {fixed} characters")
            pos += fixed
        else:
            end = data.find(GS, pos)
            end = len(data) if end < 0 else end
            value = data[pos:end]
            pos = end
        elements.append((ai, value))
    return elements, errors


def _parse_hri(text: str) -> list[tuple[str, str]] | None:
    pairs = HRI_RE.findall(text)
    if not pairs or "".join(f"({a}){v}" for a, v in pairs) != text.strip():
        return None
    return pairs


def _describe(ai: str, value: str, errors: list[str]) -> dict:
    entry: dict = {"ai": ai, "name": NAMES.get(ai) or MEASURES.get(ai[:3]) or NAMES.get(ai[:2]), "value": value}
    if ai in CHECK_DIGIT_AIS and not check_digit_ok(value):
        errors.append(f"AI {ai}: check digit wrong in {value!r}")
    if ai == "01" and (pub := publication(value)):
        entry.update(pub)
    if ai in DATE_AIS and re.fullmatch(r"\d{6}", value):
        yy, mm, dd = value[:2], value[2:4], value[4:]
        entry["date"] = f"20{yy}-{mm}" if dd == "00" else f"20{yy}-{mm}-{dd}"
    if ai[:2] in FOUR_DIGIT and len(ai) == 4 and ai[3].isdigit() and ai[:3] in MEASURES and value.isdigit():
        decimals = int(ai[3])
        entry["number"] = int(value) / 10 ** decimals if decimals else int(value)
    return entry


def _ean(text: str, aim: str) -> dict | None:
    m = EAN_RE.match(text)
    if not m:
        return None
    code, add_on = m.groups()
    if add_on and aim != "]E3":  # only ]E3 says an add-on follows
        return None
    # ]E0 with eight digits is UPC-E (EAN-8 is ]E4), whose check digit belongs to the expanded UPC-A.
    gtin = upc_e_to_a(code) if len(code) == 8 and aim == "]E0" else code
    errors: list[str] = []
    element = _describe("01", gtin.zfill(14), errors)
    result: dict = {"type": TYPE, "valid": not errors, "errors": errors, "gtin": gtin,
                    "hri": f"(01){element['value']}", "elements": [element]}
    if add_on:
        result["add_on"] = add_on
    return result


def match(data: bytes, aim: str | None = None) -> dict | None:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return None
    if aim in EAN_AIM:
        return _ean(text.strip(), aim)
    if text[:3] in GS1_AIM:
        aim, text = text[:3], text[3:]
    hri = None if aim in GS1_AIM else _parse_hri(text)
    if aim not in GS1_AIM and hri is None:
        return None

    errors: list[str] = []
    if hri is not None:
        elements = hri
    elif text.startswith("("):
        elements = _parse_hri(text) or []
        if not elements:
            errors.append("unparseable GS1 human-readable string")
    else:
        elements, errors = _parse_raw(text.lstrip(GS))
    described = [_describe(ai, value, errors) for ai, value in elements]
    hri_text = "".join(f"({e['ai']}){e['value']}" for e in described)
    return {"type": TYPE, "valid": not errors and bool(described), "errors": errors, "hri": hri_text,
            "elements": described}
