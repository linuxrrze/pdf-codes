"""ICAO Visible Digital Seal (VDS): signed DataMatrix on visas, German arrival attestations, residence permits,
address stickers, social insurance cards and administrative documents.

Specification: ICAO Doc 9303 Part 13 ("Visible Digital Seals") for the header and the visa / emergency travel
document profiles; BSI TR-03137 Part 1 for the German profiles and the C40 rules (Annex B), with worked
examples in Annexes C and D: https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/
Standards-und-Zertifizierung/Technische-Richtlinien/TR-nach-Thema-sortiert/tr03137/tr-03137.html
Profile tables cross-checked with BSI's reference implementation https://github.com/tsenger/vdstools
(VdsDocumentTypes.json, VdsProfileDefinitions.json, VdsHeader.kt).

    0xDC | version | issuing country (C40, 2 bytes) | signer + certificate reference (C40) |
    issue date (3) | signature date (3) | feature definition reference (1) | document type category (1) |
    message zone: tag, length, value ... | 0xFF, length, signature

- Version byte 0x02 is ICAO version 3: the signer and certificate reference are 9 C40 characters (6 bytes),
  signer (4) + certificate reference (5). Feature lengths are one byte.
- Version byte 0x03 is version 4: signer (4) + certificate reference length (2 hex digits; decimal for the
  signer DEZV) + certificate reference. Lengths are DER-encoded (0x81 nn, 0x82 nnnn).
- Some German arrival attestations carry 0x03 with the version 3 layout (noted in vdstools), so the other
  layout is tried when the declared one does not parse; that is reported as a warning.
- Dates are the integer MMDDYYYY in three big-endian bytes.

The newer ICAO "IDB" barcodes (text starting with ``RDB``) are a different format and not decoded here.
The signature is not verified.
"""

from __future__ import annotations

import datetime as dt
import re

TYPE = "icao_vds"
C40_CHARS = {3: " ", **{i: str(i - 4) for i in range(4, 14)}, **{i: chr(ord("A") + i - 14) for i in range(14, 40)}}

# (feature definition reference, document type category) -> (document, {tag: (field, coding)})
# Codings: c40, mrz (C40 with "<" for filler), utf8, byte, duration (days, months, years), hex.
_ADDRESS = {1: ("document_number", "c40"), 2: ("municipality_code", "c40"), 3: ("address", "c40")}
PROFILES: dict[tuple[int, int], tuple[str, dict[int, tuple[str, str]]]] = {
    (0x5D, 0x01): ("visa", {1: ("mrz_mrv_a", "mrz"), 2: ("mrz_mrv_b", "mrz"), 3: ("number_of_entries", "byte"),
                            4: ("duration_of_stay", "duration"), 5: ("passport_number", "c40"),
                            6: ("visa_type", "hex"), 7: ("additional_features", "hex")}),
    (0x5E, 0x03): ("emergency_travel_document", {2: ("mrz", "mrz")}),
    (0xFD, 0x02): ("arrival_attestation", {2: ("mrz", "mrz"), 3: ("azr_number", "c40")}),
    (0xFC, 0x04): ("social_insurance_card", {1: ("social_insurance_number", "c40"), 2: ("surname", "utf8"),
                                             3: ("first_name", "utf8"), 4: ("birth_name", "utf8")}),
    (0xFB, 0x06): ("residence_permit", {2: ("mrz", "mrz"), 3: ("passport_number", "c40")}),
    (0xFA, 0x06): ("residence_permit_supplementary_sheet", {4: ("mrz", "mrz"), 5: ("sheet_number", "c40")}),
    (0xF9, 0x08): ("address_sticker_id_card", _ADDRESS),
    (0xF9, 0x0C): ("address_sticker_residence_permit_card", _ADDRESS),
    (0xF8, 0x0A): ("place_of_residence_sticker_passport", {1: ("document_number", "c40"),
                                                           2: ("municipality_code", "c40"),
                                                           3: ("postal_code", "c40")}),
    # BSI TR-03171 administrative documents: tag 0 names a profile by UUID, which defines the other tags.
    (0x01, 0xC8): ("administrative_document_v8", {0: ("profile_id", "hex"), 1: ("validity_dates", "hex")}),
    (0x01, 0xC9): ("administrative_document_v9", {0: ("profile_id", "hex"), 1: ("valid_from", "utf8"),
                                                  2: ("valid_to", "utf8"), 3: ("profile_uri", "utf8"),
                                                  4: ("certificate_uri", "utf8"), 5: ("status_uri", "utf8"),
                                                  6: ("status_list_index", "int")}),
}
ADMIN_PROFILES = {
    "9a4223406d374ef99e2cf95e31a23846": ("Meldebescheinigung", {
        4: "surname", 5: "academic_degree", 6: "first_name", 7: "common_first_name", 8: "date_of_birth",
        9: "street", 10: "house_number", 11: "postal_code", 12: "city", 13: "moving_date", 14: "housing_status",
        15: "date_of_notification"}),
}
PERSONAL = {"arrival_attestation", "social_insurance_card", "residence_permit", "visa", "emergency_travel_document",
            "residence_permit_supplementary_sheet", "address_sticker_id_card", "address_sticker_residence_permit_card",
            "place_of_residence_sticker_passport", "administrative_document_v8", "administrative_document_v9"}


def c40_decode(data: bytes) -> str | None:
    """BSI TR-03137 Annex B. Returns None for anything that is not a valid C40 string."""
    if len(data) % 2:
        return None
    out = []
    for i in range(0, len(data), 2):
        hi, lo = data[i], data[i + 1]
        if hi == 0xFE:  # a single trailing character in the DataMatrix ASCII scheme (ASCII + 1)
            if i != len(data) - 2 or not 0 < lo <= 128:
                return None
            out.append(chr(lo - 1))
            continue
        v = hi * 256 + lo
        if not 1 <= v <= 64000:
            return None
        u1, rest = divmod(v - 1, 1600)
        u2, u3 = divmod(rest, 40)
        for j, u in enumerate((u1, u2, u3)):
            if u == 0 and i == len(data) - 2 and j == 2:  # Shift 1 pads the last triple
                continue
            if u not in C40_CHARS:
                return None
            out.append(C40_CHARS[u])
    return "".join(out)


def _date(data: bytes) -> str | None:
    s = f"{int.from_bytes(data, 'big'):08d}"
    try:
        return dt.date(int(s[4:]), int(s[:2]), int(s[2:4])).isoformat()
    except ValueError:
        return None


def _length(data: bytes, pos: int, der: bool) -> tuple[int, int] | None:
    if pos >= len(data):
        return None
    first = data[pos]
    if not der or first < 0x80:
        return first, pos + 1
    n = first & 0x7F
    if not 1 <= n <= 2 or pos + 1 + n > len(data):
        return None
    return int.from_bytes(data[pos + 1:pos + 1 + n], "big"), pos + 1 + n


def _header(data: bytes, v4: bool) -> dict | None:
    if v4:
        head = c40_decode(data[4:8])
        if head is None or len(head) != 6:
            return None
        signer, length = head[:4], head[4:]
        try:
            n = int(length, 10 if signer == "DEZV" else 16)
        except ValueError:
            return None
        end = 8 + ((n - 1) // 3) * 2 + 2 if n else 8
        cert = c40_decode(data[8:end]) if n else ""
    else:
        end = 10
        both = c40_decode(data[4:10])
        if both is None or len(both) != 9:
            return None
        signer, cert = both[:4], both[4:]
    if cert is None or len(data) < end + 8 or not re.fullmatch(r"[A-Z0-9 ]{4}", signer):
        return None
    issue, signed = _date(data[end:end + 3]), _date(data[end + 3:end + 6])
    if issue is None or signed is None:
        return None
    return {"signer": signer, "certificate_reference": cert, "issue_date": issue, "signature_date": signed,
            "feature_definition_reference": data[end + 6], "document_type_category": data[end + 7],
            "_end": end + 8}


def _zones(data: bytes, pos: int, der: bool) -> tuple[list[tuple[int, bytes]], bytes, int] | None:
    """Message zone features and the signature; None unless the bytes form TLVs ending in a signature."""
    features = []
    while pos < len(data):
        tag = data[pos]
        length = _length(data, pos + 1, der)
        if length is None:
            return None
        n, start = length
        if start + n > len(data):
            return None
        if tag == 0xFF:
            return features, data[start:start + n], len(data) - (start + n)
        features.append((tag, data[start:start + n]))
        pos = start + n
    return None


def _value(raw: bytes, coding: str) -> object:
    if coding in ("c40", "mrz"):
        text = c40_decode(raw)
        if text is None:
            return {"hex": raw.hex()}
        if coding == "mrz":
            text = text.replace(" ", "<")
            half = len(text) // 2
            return [text[:half], text[half:]]
        return text.strip()
    if coding == "utf8":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"hex": raw.hex()}
    if coding in ("byte", "int"):
        return int.from_bytes(raw, "big")
    if coding == "duration" and len(raw) == 3:
        return {"days": raw[0], "months": raw[1], "years": raw[2]}
    return raw.hex()


def match(data: bytes, aim: str | None = None) -> dict | None:
    if len(data) < 18 or data[0] != 0xDC or data[1] not in (0x02, 0x03):
        return None
    country = c40_decode(data[2:4])
    if country is None or not re.fullmatch(r"[A-Z][A-Z ]{2}", country):
        return None

    declared_v4 = data[1] == 0x03
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [],
                    "version": 4 if declared_v4 else 3, "issuing_country": country.replace(" ", "<")}
    parsed = None
    for v4 in (declared_v4, not declared_v4):
        header = _header(data, v4)
        zones = header and _zones(data, header["_end"], v4)
        if zones:
            parsed = header, zones
            if v4 != declared_v4:
                result["warnings"].append(f"version byte {data[1]:#04x} but the header has the version "
                                          f"{4 if v4 else 3} layout")
            break
    if parsed is None:
        result["valid"] = False
        result["errors"].append("header, message zone or signature cannot be parsed")
        return result

    header, (features, signature, trailing) = parsed
    del header["_end"]
    ref, category = header["feature_definition_reference"], header["document_type_category"]
    result.update(header)
    result["feature_definition_reference"] = f"{ref:#04x}"
    result["document_type_category"] = f"{category:#04x}"
    document, table = PROFILES.get((ref, category), (None, {}))
    if document:
        result["document"] = document
    else:
        result["warnings"].append(f"unknown document type {ref:#04x}/{category:#04x}")

    decoded: dict = {}
    unknown = []
    admin_names: dict[int, str] = {}
    for tag, raw in features:
        if tag in table:
            name, coding = table[tag]
            decoded[name] = _value(raw, coding)
            if name == "profile_id" and decoded[name] in ADMIN_PROFILES:
                result["profile"], admin_names = ADMIN_PROFILES[decoded[name]]
        elif tag in admin_names:
            decoded[admin_names[tag]] = _value(raw, "utf8")
        else:
            # Unknown tags have no coding; offer the reading the document family uses for text.
            entry: dict = {"tag": tag, "hex": raw.hex()}
            if document and document.startswith("administrative_document"):
                text, key = _value(raw, "utf8"), "utf8"
            else:
                text, key = c40_decode(raw), "c40"
            if isinstance(text, str) and text.strip():
                entry[key] = text
            unknown.append(entry)
    if not features:
        result["errors"].append("the message zone has no features")
    result["features"] = decoded
    if unknown:
        result["unknown_features"] = unknown
    result["signature_length"] = len(signature)
    result["signature_verified"] = None
    if trailing:
        result["warnings"].append(f"{trailing} bytes after the signature")
    if document in PERSONAL:
        result["note"] = "contains personal data from an identity or residence document; signature not verified"
    result["valid"] = not result["errors"]
    return result
