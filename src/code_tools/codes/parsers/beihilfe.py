"""QR code on Beihilfe forms: applications ("H001") and the Beihilfe office's notices ("X_H001").

No specification is published. The layout was inferred from 13 documents (2016-2021), each with one code per
page, fields separated by ";":

    H001;V 10.2016;<UUID>;<page>;<8 digits>;<surname>;<first name>;

- "H001" was on applications, "X_H001" on notices (approvals, assessments);
- "V MM.YYYY" reads as the form version (month.year); it changed over the years, but notices and applications
  had their own series;
- the UUID was the same on every page of one document and different between documents;
- the page number counted the pages of the document;
- the 8-digit number was the same on every document, so it is most likely the applicant's personnel number.

An older application (2013 form) had only "H001;" plus the form version.
"""

from __future__ import annotations

import re

TYPE = "beihilfe_form"
HEADER_RE = re.compile(r"^(X_)?H(\d{3});")
VERSION_RE = re.compile(r"^(?:V\s*)?(\d{2})\.(\d{4})$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CAVEAT = "inferred from 13 documents (2016-2021); not an official decoding"


def match(data: bytes, aim: str | None = None) -> dict | None:
    if aim is not None and not aim.startswith("]Q"):  # QR code only
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("iso-8859-1")
    m = HEADER_RE.match(text)
    if not m:
        return None
    fields = [f.strip() for f in text.split(";")]
    if fields and fields[-1] == "":
        fields.pop()  # the code ends with ";"
    version = VERSION_RE.match(fields[1]) if len(fields) > 1 else None
    if version is None:
        return None  # "H001;" alone is too weak a header

    result: dict = {"type": TYPE, "valid": True, "errors": [], "warnings": [],
                    "note": "contains the applicant's name and probably their personnel number"}
    inferred: dict = {
        "document": "notice" if m.group(1) else "application",
        "form": f"H{m.group(2)}",
        "form_version": f"{version.group(2)}-{version.group(1)}",
    }
    rest = fields[2:]
    if rest:
        names = ("document_id", "page", "person_number", "surname", "first_name")
        values = dict(zip(names, rest))
        if len(rest) != len(names):
            result["warnings"].append(f"{len(fields)} fields, the known layout has {len(names) + 2}")
        if "document_id" in values and not UUID_RE.match(values["document_id"]):
            result["errors"].append(f"document ID is not a UUID: {values['document_id']!r}")
        if "page" in values:
            if values["page"].isdigit():
                values["page"] = int(values["page"])
            else:
                result["errors"].append(f"page is not a number: {values['page']!r}")
        if "person_number" in values and not re.fullmatch(r"\d{8}", values["person_number"]):
            result["warnings"].append(f"expected an 8-digit number, got {values['person_number']!r}")
        inferred.update({k: v for k, v in values.items() if v != ""})
    inferred["caveat"] = CAVEAT
    result["inferred"] = inferred
    result["valid"] = not result["errors"]
    return result
