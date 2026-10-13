"""UIC 918.3 rail tickets (Aztec code, e.g. Deutsche Bahn online tickets).

Container ("#UT"):
    "#UT" | version (2) | issuer RICS code (4) | key ID (5) | signature (50 bytes for version 01, 64 for 02)
    | length of compressed data (4 digits) | zlib-compressed records
Each record: ID (6) | version (2) | length including this 12-byte header (4 digits) | data.

The official specification (UIC leaflet 918-3) is not freely available. The layouts used here follow the
open-source decoder https://github.com/justusjonas74/uic-918-3 (MIT licence):
    U_HEAD v01   issuer (4), order number (8), padding (12), creation time DDMMYYYYHHMM (12), flags (1),
                 language (2), second language (2)
    U_TLAY v01   layout standard (4, "RCT2"), number of fields (4), then per field: line (2), column (2),
                 height (2), width (2), style (1), text length (4), text
    0080BL v02/03  Deutsche Bahn: 2 unknown bytes, number of orders (1), the orders, number of S-blocks (2),
                 then S-blocks: "S" + type (3 digits) + length (4) + text

The signature is not verified: that needs the issuers' public keys (https://railpublickey.uic.org/).
"""

from __future__ import annotations

import re
import zlib

TYPE = "uic_ticket"
SIGNATURE_LENGTH = {"01": 50, "02": 64}
MAX_DECOMPRESSED = 1024 * 1024
ISSUERS = {"0080": "Deutsche Bahn"}  # RICS company codes; only the one seen in samples so far

# Deutsche Bahn S-block types, from the reference decoder's enums.ts.
DB_SBLOCK_NAMES = {
    1: "Preismodell", 2: "Produktklasse Gesamtticket", 3: "Produktklasse Hinfahrt",
    4: "Produktklasse Rückfahrt", 9: "Passagiere", 12: "Kinder", 14: "Klasse", 15: "H-Start-Bf",
    16: "H-Ziel-Bf", 17: "R-Start-Bf", 18: "R-Ziel-Bf", 19: "Vorgangsnr./Flugscheinnr.",
    20: "Vertragspartner", 21: "VIA", 23: "Personenname", 26: "Preisart", 27: "Ausweis-ID",
    28: "Vorname, Name", 31: "Gueltig von", 32: "Gueltig bis", 35: "Start-Bf-ID", 36: "Ziel-Bf-ID",
    40: "Anzahl Personen", 41: "TBD EFS Anzahl",
}
# Per order ("Auftrag") in 0080BL: version 02 = certificate (11), padding (11), valid from (8), valid to (8),
# serial (8); version 03 = valid from (8), valid to (8), serial (10).
DB_ORDER_LAYOUT = {
    "02": (("certificate", 11), ("padding", 11), ("valid_from", 8), ("valid_to", 8), ("serial", 8)),
    "03": (("valid_from", 8), ("valid_to", 8), ("serial", 10)),
}


class _Malformed(ValueError):
    pass


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1")


def _int(raw: bytes, what: str) -> int:
    if not raw.isdigit():
        raise _Malformed(f"{what}: expected digits, got {raw!r}")
    return int(raw)


def _date(ddmmyyyy: str) -> str | None:
    if re.fullmatch(r"\d{8}", ddmmyyyy):
        return f"{ddmmyyyy[4:8]}-{ddmmyyyy[2:4]}-{ddmmyyyy[:2]}"
    return None


def _records(data: bytes) -> list[tuple[str, str, bytes]]:
    records, pos = [], 0
    while pos < len(data):
        if len(data) - pos < 12:
            raise _Malformed(f"truncated record header at offset {pos}")
        rid, version = _text(data[pos:pos + 6]), _text(data[pos + 6:pos + 8])
        length = _int(data[pos + 8:pos + 12], f"record {rid} length")
        if length < 12 or pos + length > len(data):
            raise _Malformed(f"record {rid}: length {length} does not fit")
        records.append((rid, version, data[pos + 12:pos + length]))
        pos += length
    return records


def _u_head(body: bytes) -> dict:
    created = _text(body[24:36])
    iso = None
    if re.fullmatch(r"\d{12}", created):
        iso = f"{created[4:8]}-{created[2:4]}-{created[:2]}T{created[8:10]}:{created[10:12]}"
    return {"issuer": _text(body[0:4]), "order_number": _text(body[4:12]).strip("\0 "),
            "created": iso, "flags": _text(body[36:37]), "language": _text(body[37:39]),
            "language_2": _text(body[39:41]) or None}


def _u_tlay(body: bytes) -> dict:
    standard, count = _text(body[0:4]), _int(body[4:8], "U_TLAY field count")
    fields, pos = [], 8
    for _ in range(count):
        head = body[pos:pos + 13]
        if len(head) < 13:
            raise _Malformed("U_TLAY: truncated field")
        length = _int(head[9:13], "U_TLAY text length")
        fields.append({"line": _int(head[0:2], "line"), "column": _int(head[2:4], "column"),
                       "height": _int(head[4:6], "height"), "width": _int(head[6:8], "width"),
                       "style": _int(head[8:9], "style"), "text": _text(body[pos + 13:pos + 13 + length])})
        pos += 13 + length
    fields.sort(key=lambda f: (f["line"], f["column"]))
    return {"standard": standard, "fields": fields}


def _db_bl(version: str, body: bytes) -> dict:
    layout = DB_ORDER_LAYOUT.get(version)
    if layout is None:
        raise _Malformed(f"0080BL version {version} is not supported")
    order_len = sum(n for _, n in layout)
    count = _int(body[2:3], "0080BL order count")
    orders, pos = [], 3
    for _ in range(count):
        order, off = {}, pos
        for name, n in layout:
            order[name] = _text(body[off:off + n]).strip("\0 ")
            off += n
        for key in ("valid_from", "valid_to"):
            order[key] = _date(order[key]) or order[key]
        order.pop("padding", None)
        orders.append(order)
        pos += order_len
    n_blocks = _int(body[pos:pos + 2], "0080BL S-block count")
    pos += 2
    blocks = {}
    for _ in range(n_blocks):
        if body[pos:pos + 1] != b"S":
            raise _Malformed(f"0080BL: expected an S-block at offset {pos}")
        kind = _int(body[pos + 1:pos + 4], "S-block type")
        length = _int(body[pos + 4:pos + 8], "S-block length")
        blocks[DB_SBLOCK_NAMES.get(kind, f"S{kind:03d}")] = _text(body[pos + 8:pos + 8 + length])
        pos += 8 + length
    return {"unknown_prefix": _text(body[0:2]), "orders": orders, "fields": blocks}


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not data.startswith(b"#UT"):
        return None
    version, issuer, key_id = _text(data[3:5]), _text(data[5:9]), _text(data[9:14])
    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "version": version,
                    "issuer_code": issuer, "issuer": ISSUERS.get(issuer), "key_id": key_id,
                    "signature_verified": None,
                    "note": "UIC 918.3 rail ticket; signature not verified; usually contains the traveller's name"}
    try:
        sig_len = SIGNATURE_LENGTH.get(version)
        if sig_len is None:
            raise _Malformed(f"unknown container version {version!r}")
        pos = 14 + sig_len
        length = _int(data[pos:pos + 4], "compressed length")
        compressed = data[pos + 4:pos + 4 + length]
        if len(compressed) != length:
            raise _Malformed(f"compressed data is {len(compressed)} bytes, header says {length}")
        inflater = zlib.decompressobj()
        try:
            raw = inflater.decompress(compressed, MAX_DECOMPRESSED)
        except zlib.error as exc:
            raise _Malformed(f"zlib: {exc}") from exc
        if inflater.unconsumed_tail:
            raise _Malformed(f"decompressed data exceeds {MAX_DECOMPRESSED} bytes")
        records = _records(raw)
    except _Malformed as exc:
        result["valid"] = False
        result["errors"].append(str(exc))
        return result

    result["records"] = [{"id": rid, "version": ver, "length": len(body) + 12} for rid, ver, body in records]
    for rid, ver, body in records:
        try:
            if rid == "U_HEAD":
                result["header"] = _u_head(body)
            elif rid == "U_TLAY":
                result["layout"] = _u_tlay(body)
            elif rid == "0080BL":
                result["deutsche_bahn"] = _db_bl(ver, body)
            else:
                result["warnings"].append(f"record {rid} v{ver} is not decoded")
        except (_Malformed, IndexError) as exc:
            result["warnings"].append(f"record {rid} v{ver}: {exc}")
    return result
