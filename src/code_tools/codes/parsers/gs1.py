"""GS1 element strings (GS1-128, GS1 DataMatrix, GS1 QR, GS1 DataBar, GS1 DotCode).

Recognised by the AIM symbology identifier that marks FNC1-in-first-position (]C1 ]d2 ]Q3 ]e0 ]J1), by such an
identifier at the start of the payload, or by the human-readable "(01)...(17)..." form.
"""

from __future__ import annotations

import re

TYPE = "gs1"
GS1_AIM = ("]C1", "]d2", "]Q3", "]e0", "]J1")
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
    if ai in DATE_AIS and re.fullmatch(r"\d{6}", value):
        yy, mm, dd = value[:2], value[2:4], value[4:]
        entry["date"] = f"20{yy}-{mm}" if dd == "00" else f"20{yy}-{mm}-{dd}"
    if ai[:2] in FOUR_DIGIT and len(ai) == 4 and ai[3].isdigit() and ai[:3] in MEASURES and value.isdigit():
        decimals = int(ai[3])
        entry["number"] = int(value) / 10 ** decimals if decimals else int(value)
    return entry


def match(data: bytes, aim: str | None = None) -> dict | None:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return None
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
