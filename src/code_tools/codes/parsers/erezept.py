"""German electronic prescription (E-Rezept) token, printed as a DataMatrix on the patient printout.

Specification: gematik, gemSpec_DM_eRp (data model) and gemSpec_FD_eRp (E-Rezept-Fachdienst), the
"E-Rezept-Token"; the prescription ID profile is https://gematik.de/fhir/ti/StructureDefinition/e-prescription-id

    {"urls": ["Task/<prescription ID>/$accept?ac=<access code>", ...]}

One code per prescription, plus a collective code ("Sammelcode") with up to three tokens.

- Prescription ID: ``aaa.bbb.bbb.bbb.bbb.cc``. ``aaa`` is the flow type (the kind of prescription),
  ``bbb...`` a running number, ``cc`` the check digits by ISO 7064 Mod 97-10 over the first 15 digits.
- Access code: 64 hex digits (256 bits). Together with the ID it lets anyone redeem the prescription.
"""

from __future__ import annotations

import json
import re

TYPE = "erezept"
URL_RE = re.compile(r"^Task/(\d{3}(?:\.\d{3}){4}\.\d{2})/\$accept\?ac=([0-9A-Fa-f]*)$")
FLOW_TYPES = {
    "160": "Muster 16 (statutory insurance, pharmacy-only medicines)",
    "162": "Muster 16 (statutory insurance, digital health applications, DiGA)",
    "169": "Muster 16 (statutory insurance, direct assignment to a pharmacy)",
    "200": "PKV (private insurance, pharmacy-only medicines)",
    "209": "PKV (private insurance, direct assignment to a pharmacy)",
}


def prescription_id_valid(prescription_id: str) -> bool:
    """ISO 7064 Mod 97-10 over the 15 digits before the check digits."""
    digits = prescription_id.replace(".", "")
    if not re.fullmatch(r"\d{17}", digits):
        return False
    return 98 - int(digits[:15]) * 100 % 97 == int(digits[15:])


def match(data: bytes, aim: str | None = None) -> dict | None:
    if aim is not None and not aim.startswith("]d"):  # DataMatrix only
        return None
    if not data.lstrip().startswith(b"{") or b"Task/" not in data:
        return None
    try:
        token = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(token, dict) or not isinstance(token.get("urls"), list):
        return None
    urls = token["urls"]
    if not urls or not all(isinstance(u, str) and u.startswith("Task/") for u in urls):
        return None

    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [], "prescriptions": [],
                    "note": "the access code redeems the prescription: treat the code like the prescription itself"}
    if len(urls) > 3:
        result["warnings"].append(f"{len(urls)} prescriptions; a collective code holds at most 3")
    if set(token) != {"urls"}:
        result["warnings"].append(f"unexpected keys: {sorted(set(token) - {'urls'})}")
    for i, url in enumerate(urls, 1):
        m = URL_RE.match(url)
        if not m:
            result["errors"].append(f"token {i}: expected Task/<ID>/$accept?ac=<access code>, got {url!r}")
            continue
        prescription_id, access_code = m.groups()
        flow_type = prescription_id[:3]
        entry = {"prescription_id": prescription_id, "flow_type": flow_type,
                 "flow_type_name": FLOW_TYPES.get(flow_type), "access_code": access_code}
        if entry["flow_type_name"] is None:
            del entry["flow_type_name"]
            result["warnings"].append(f"token {i}: unknown flow type {flow_type}")
        if not prescription_id_valid(prescription_id):
            result["errors"].append(f"token {i}: check digits of prescription ID {prescription_id} are wrong")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", access_code):
            result["errors"].append(f"token {i}: access code must be 64 hex digits, got {len(access_code)}")
        result["prescriptions"].append(entry)
    result["valid"] = not result["errors"]
    return result
