"""General-purpose payloads: vCard, MECARD, WiFi, mailto, tel, sms, geo, URL, plus header-only detection of
EU digital COVID certificates, the German medication plan (BMP), Deutsche Post
franking marks and the eA/eP codes of German private medical invoices."""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse

from .common import decode_text


def _text(data: bytes) -> str | None:
    return decode_text(data)


def _split_escaped(s: str, sep: str) -> list[str]:
    """Split on ``sep`` honouring backslash escapes, as used by WIFI: and MECARD:."""
    parts, cur, it = [], [], iter(s)
    for ch in it:
        if ch == "\\":
            cur.append(next(it, ""))
        elif ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _fields(body: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in _split_escaped(body, ";"):
        if ":" in part:
            key, value = part.split(":", 1)
            out.setdefault(key.upper(), []).append(value)
    return out


def vcard(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.lstrip().upper().startswith("BEGIN:VCARD"):
        return None
    # Unfold continuation lines (RFC 6350 3.2), then read NAME;PARAMS:VALUE lines.
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    props: dict[str, list[str]] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        props.setdefault(key.split(";", 1)[0].upper(), []).append(value)
    errors = [] if "END" in props else ["missing END:VCARD"]

    def first(key: str) -> str | None:
        return props.get(key, [None])[0]

    return {"type": "vcard", "valid": not errors, "errors": errors, "version": first("VERSION"),
            "name": first("FN") or first("N"), "organisation": first("ORG"), "title": first("TITLE"),
            "phones": props.get("TEL", []), "emails": props.get("EMAIL", []), "urls": props.get("URL", []),
            "addresses": props.get("ADR", []), "note": first("NOTE")}


def mecard(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.upper().startswith("MECARD:"):
        return None
    f = _fields(text[7:])
    return {"type": "mecard", "valid": "N" in f, "errors": [] if "N" in f else ["name (N:) missing"],
            "name": f.get("N", [None])[0], "phones": f.get("TEL", []), "emails": f.get("EMAIL", []),
            "urls": f.get("URL", []), "address": f.get("ADR", [None])[0], "note": f.get("NOTE", [None])[0]}


def wifi(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.upper().startswith("WIFI:"):
        return None
    f = {k: v[0] for k, v in _fields(text[5:]).items()}
    errors = [] if f.get("S") else ["SSID (S:) missing"]
    return {"type": "wifi", "valid": not errors, "errors": errors, "ssid": f.get("S"),
            "security": f.get("T") or "nopass", "password": f.get("P"), "hidden": f.get("H", "").lower() == "true"}


def mailto(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.lower().startswith("mailto:"):
        return None
    parsed = urllib.parse.urlsplit(text.strip())
    query = urllib.parse.parse_qs(parsed.query)
    to = urllib.parse.unquote(parsed.path)
    errors = [] if "@" in to or query.get("to") else ["no recipient"]
    return {"type": "mailto", "valid": not errors, "errors": errors, "to": to or None,
            "subject": query.get("subject", [None])[0], "body": query.get("body", [None])[0]}


def tel(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.lower().startswith("tel:"):
        return None
    number = text[4:].strip()
    ok = bool(re.fullmatch(r"\+?[\d\s()./-]{3,}", number))
    return {"type": "tel", "valid": ok, "errors": [] if ok else ["not a phone number"], "number": number}


def sms(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text:
        return None
    m = re.match(r"(?i)^(?:smsto|sms):([^:?]*)(?:[:?](?:body=)?(.*))?$", text.strip(), re.DOTALL)
    if not m:
        return None
    return {"type": "sms", "valid": bool(m.group(1)), "errors": [] if m.group(1) else ["no number"],
            "number": m.group(1), "body": m.group(2)}


def geo(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not text.lower().startswith("geo:"):
        return None
    m = re.match(r"^geo:(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(-?\d+(?:\.\d+)?))?", text.strip(), re.IGNORECASE)
    if not m:
        return {"type": "geo", "valid": False, "errors": ["malformed coordinates"]}
    lat, lon = float(m.group(1)), float(m.group(2))
    ok = -90 <= lat <= 90 and -180 <= lon <= 180
    return {"type": "geo", "valid": ok, "errors": [] if ok else ["coordinates out of range"],
            "latitude": lat, "longitude": lon, "altitude": float(m.group(3)) if m.group(3) else None}


def url(data: bytes, aim=None) -> dict | None:
    text = _text(data)
    if not text or not re.match(r"(?i)^https?://", text.strip()) or re.search(r"\s", text.strip()):
        return None
    parsed = urllib.parse.urlsplit(text.strip())
    ok = bool(parsed.hostname)
    return {"type": "url", "valid": ok, "errors": [] if ok else ["no host"], "url": text.strip(),
            "scheme": parsed.scheme.lower(), "host": parsed.hostname}


def eu_dcc(data: bytes, aim=None) -> dict | None:
    if not data.startswith(b"HC1:"):
        return None
    return {"type": "eu_dcc", "valid": True, "errors": [],
            "note": "EU Digital COVID Certificate (base45/zlib/COSE); not decoded here"}


def medication_plan(data: bytes, aim=None) -> dict | None:
    text = _text(data) or data.decode("iso-8859-1", "replace")
    if not text.lstrip().startswith("<MP"):
        return None
    m = re.search(r'\bv="(\d+)"', text)
    return {"type": "medication_plan", "valid": text.rstrip().endswith("</MP>"),
            "errors": [] if text.rstrip().endswith("</MP>") else ["truncated (no </MP>)"],
            "version": m.group(1) if m else None,
            "note": "German Bundeseinheitlicher Medikationsplan (BMP) XML"}


def _day_of_year_date(value: int) -> str | None:
    """DDDYY packed as one integer (e.g. 28226 = day 282 of 2026) -> ISO date."""
    day, year = divmod(value, 100)
    try:
        start = dt.date(2000 + year, 1, 1)
    except ValueError:
        return None
    date = start + dt.timedelta(days=day - 1)
    return date.isoformat() if 1 <= day and date.year == start.year else None


def deutsche_post_franking(data: bytes, aim=None) -> dict | None:
    """Deutsche Post postage DataMatrix ("Matrixcode", e.g. Internetmarke, FRANKIT, DMC stamps).

    "DEA" = DE (Germany) + A (Deutsche Post), as documented by Deutsche Post. The rest of the layout is not
    published. For the 42-byte layout, these fields were inferred by comparing 13 letters (2011-2026, several
    senders) with the text printed next to the code and with Deutsche Post's historical postage rates; they are
    reported under "inferred" and are not an official decoding:
      byte 4       rises over time (0x19 in 2011 ... 0x3b in 2026), presumably a format or key version
      bytes 10-11  postage in cents (big-endian); matched the official rate of the mailing date every time
      bytes 12-13  mailing date as DDDYY: day of year * 100 + two-digit year (big-endian)
      bytes 17-18  the middle number of the printed line "*...*NNNN*...*"
      bytes 19-21  the start of the printed hex line ("E9 ... 65 9..."); bytes 20-21 look like a counter
      bytes 22-41  varies by sender: zeros, a run of ASCII digits (a sender reference), or spaces followed by
                   "A" C4 02 and four bytes that match no checksum (presumably a signature)
    """
    if not data.startswith(b"DEA") or (aim is not None and not aim.startswith("]d")):
        return None
    body = data[3:]
    # The payload is binary (crypto string, hash). Requiring that avoids matching text such as "DEAR ...".
    if not body or all(32 <= b < 127 or b in (9, 10, 13) for b in body):
        return None
    result = {"type": "deutsche_post_franking", "valid": True, "errors": [], "length": len(data),
              "note": "Deutsche Post franking mark (DE + carrier A); the field layout is not public"}
    if len(data) == 42:
        cents = int.from_bytes(data[10:12], "big")
        inferred = {
            "postage": f"{cents // 100}.{cents % 100:02d}",
            "currency": "EUR",
            "date": _day_of_year_date(int.from_bytes(data[12:14], "big")),
            "printed_number": int.from_bytes(data[17:19], "big"),
            "printed_id_start": data[19:22].hex().upper(),
            "version_byte": f"{data[4]:02X}",
        }
        digits = re.findall(rb"\d{8,}", data[22:])
        if digits:
            inferred["sender_reference"] = digits[0].decode()
        inferred["caveat"] = ("inferred from 13 letters (2011-2026) by comparison with the printed text and "
                              "the official postage rates; not an official decoding")
        result["inferred"] = inferred
    return result


# "_" occurs in an older layout seen on 2018-2019 lab invoices: eP<18 digits>_1_au_<9 digits><base64><10 digits>.
PKV_CODE_RE = re.compile(r"^e([AP])\d[0-9A-Za-z+/=_]{20,}$")
PKV_KINDS = {
    "A": ("elektronischer Abrechnungscode", "personal data: invoice recipient's address, patient's date of birth"),
    "P": ("elektronischer Positionscode", "the invoice data needed for machine processing, without personal data"),
}


def pkv_invoice_code(data: bytes, aim=None) -> dict | None:
    """eA/eP codes on German private medical invoices (PKV and Beihilfe industry scheme).

    Printed as DataMatrix: eA top right, eP bottom left. The two are only usable together, and their
    content is encrypted for the insurers' and Beihilfe apps, so it is recognised but not decoded.
    Source: https://helpdesk.lemniscus.de/docs/rechnung-mit-ea-ep-codes
    """
    if aim is not None and not aim.startswith("]d"):
        return None
    text = _text(data)
    if not text:
        return None
    m = PKV_CODE_RE.match(text.strip())
    if not m:
        return None
    name, contents = PKV_KINDS[m.group(1)]
    return {"type": "pkv_invoice_code", "valid": True, "errors": [], "code": f"e{m.group(1)}",
            "name": name, "contents": contents,
            "note": "encrypted; only readable by the insurers' and Beihilfe apps. The eA code contains "
                    "personal data, so treat it like the invoice itself"}
