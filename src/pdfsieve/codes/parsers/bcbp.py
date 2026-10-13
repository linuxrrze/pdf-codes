"""IATA Bar Coded Boarding Pass (BCBP), format "M" (IATA Resolution 792).

Mandatory part (fixed width): format code "M" (1), number of legs (1), passenger name (20), electronic ticket
indicator (1), then per leg: PNR (7), from (3), to (3), operating carrier (3), flight number (5), date of flight
as day of year (3), compartment code (1), seat (4), check-in sequence number (5), passenger status (1), size of
the leg's conditional data in hex (2).
Conditional part of the first leg: ">" (1), version (1), size of the unique part in hex (2), then passenger
description (1), source of check-in (1), source of issuance (1), date of issue (4: last digit of year + day of
year), document type (1), issuer (3), baggage tags (3 x 13).
Conditional part of every leg: size in hex (2), airline numeric code (3), document serial number (10), selectee
indicator (1), international documentation verification (1), marketing carrier (3), frequent flyer airline (3),
frequent flyer number (16), ID/AD indicator (1), free baggage allowance (3), fast track (1); the rest of the leg's
conditional data is for individual airline use.
Optional security data after the last leg: "^" (1), type (1), size in hex (2), data.

Resolution 792 itself is not freely available. Item numbers and the meaning of the size fields are in IATA's
BCBP Implementation Guide (7th edition); the field lengths follow https://github.com/georgesmith46/bcbp (MIT).
"""

from __future__ import annotations

import re

TYPE = "iata_bcbp"
LEG_FIXED = (("pnr", 7), ("from", 3), ("to", 3), ("carrier", 3), ("flight_number", 5), ("day_of_year", 3),
             ("compartment", 1), ("seat", 4), ("check_in_sequence", 5), ("passenger_status", 1))
UNIQUE_CONDITIONAL = (("passenger_description", 1), ("check_in_source", 1), ("issuance_source", 1),
                      ("issue_date", 4), ("document_type", 1), ("issuer", 3), ("baggage_tag", 13),
                      ("baggage_tag_2", 13), ("baggage_tag_3", 13))
REPEATED_CONDITIONAL = (("airline_numeric_code", 3), ("document_serial", 10), ("selectee", 1),
                        ("documentation_verification", 1), ("marketing_carrier", 3),
                        ("frequent_flyer_airline", 3), ("frequent_flyer_number", 16), ("id_ad_indicator", 1),
                        ("free_baggage_allowance", 3), ("fast_track", 1))


class _Malformed(ValueError):
    pass


class _Reader:
    def __init__(self, text: str):
        self.text, self.pos = text, 0

    def take(self, n: int, what: str, required: bool = True) -> str:
        value = self.text[self.pos:self.pos + n]
        if required and len(value) < n:
            raise _Malformed(f"{what}: expected {n} characters at offset {self.pos}")
        self.pos += len(value)
        return value

    def hex_size(self, what: str) -> int:
        raw = self.take(2, what)
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", raw):
            raise _Malformed(f"{what}: expected two hex digits, got {raw!r}")
        return int(raw, 16)

    def rest(self) -> str:
        value = self.text[self.pos:]
        self.pos = len(self.text)
        return value


def _fields(reader: _Reader, layout) -> dict:
    """Read fixed-width items; a section may legally end early, leaving later items absent."""
    out = {}
    for name, n in layout:
        value = reader.take(n, name, required=False)
        if value.strip():
            out[name] = value.strip()
    return out


def _flight(leg: dict) -> dict:
    if "flight_number" in leg:
        leg["flight_number"] = leg["flight_number"].lstrip("0") or "0"
    day = leg.get("day_of_year", "")
    if day.isdigit():
        leg["day_of_year"] = int(day)
    return leg


def match(data: bytes, aim: str | None = None) -> dict | None:
    if not re.match(rb"M[1-9]", data):
        return None
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        text = data.decode("iso-8859-1")
    if len(text) < 60:
        return None

    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [],
                    "note": "IATA boarding pass; contains the passenger's name and booking reference"}
    r = _Reader(text)
    try:
        r.take(1, "format code")
        legs_count = int(r.take(1, "number of legs"))
        result["passenger_name"] = r.take(20, "passenger name").strip()
        result["electronic_ticket"] = r.take(1, "electronic ticket indicator") == "E"
        legs = []
        for index in range(legs_count):
            leg = {name: r.take(n, name).strip() for name, n in LEG_FIXED}
            size = r.hex_size("conditional size")
            section = _Reader(r.take(size, "conditional data"))
            if index == 0 and section.text.startswith(">"):
                section.take(1, "version indicator")
                result["version"] = section.take(1, "version")
                unique = _Reader(section.take(section.hex_size("unique size"), "unique conditional data"))
                result.update(_fields(unique, UNIQUE_CONDITIONAL))
            if section.pos < len(section.text):
                repeated = _Reader(section.take(section.hex_size("repeated size"), "repeated conditional data"))
                leg.update(_fields(repeated, REPEATED_CONDITIONAL))
                airline = section.rest()
                if airline.strip():
                    leg["airline_use"] = airline
            legs.append(_flight({k: v for k, v in leg.items() if v != ""}))
        result["legs"] = legs
        if r.pos < len(text) and text[r.pos] == "^":
            r.take(1, "security indicator")
            result["security_data_type"] = r.take(1, "security data type")
            size = r.hex_size("security data size")
            result["security_data_length"] = len(r.take(size, "security data"))
        if r.pos < len(text):
            result["warnings"].append(f"{len(text) - r.pos} unexpected trailing characters")
    except (_Malformed, ValueError) as exc:
        result["valid"] = False
        result["errors"].append(str(exc))
    # The guide says the document type tells an itinerary receipt from a boarding pass; these are the two
    # letters seen in practice (the full code list is in Resolution 792, Attachment C).
    result["document_kind"] = {"B": "boarding pass", "I": "itinerary receipt"}.get(result.get("document_type"))
    issue = result.get("issue_date", "")
    if re.fullmatch(r"\d{4}", issue):
        result["issue_date"] = {"year_last_digit": int(issue[0]), "day_of_year": int(issue[1:])}
    return result
