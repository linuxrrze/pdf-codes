"""Detect ZUGFeRD / Factur-X / XRechnung in a PDF from three independent signals.

1. The embedded file: its name and AFRelationship.
2. The XMP metadata: the ZUGFeRD/Factur-X extension schema and PDF/A identification.
3. The XML itself: syntax and specification identifier (URN). This one decides the profile.

Disagreements between the signals are reported as warnings, never silently resolved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pikepdf
from lxml import etree

from ..core.attachments import Attachment, find_attachments
from ..core.xmp import parse_xmp, read_xmp
from .profiles import InvoiceXmlInfo, inspect_xml, normalise_xmp_level

# Standard attachment names, in order of preference, with the standard they belong to.
KNOWN_NAMES = {
    "factur-x.xml": "Factur-X / ZUGFeRD 2.1+",
    "xrechnung.xml": "Factur-X / ZUGFeRD 2.1+",
    "zugferd-invoice.xml": "ZUGFeRD 2.0",
    "ZUGFeRD-invoice.xml": "ZUGFeRD 1.0",
}
XMP_NAMESPACE_STANDARD = {
    "ferd": "ZUGFeRD 1.0",
    "zugferd": "ZUGFeRD 2.0",
    "factur-x": "Factur-X / ZUGFeRD 2.1+",
}
VALID_RELATIONSHIPS = {"Alternative", "Data", "Source"}
DEFAULT_MAX_XML_BYTES = 64 * 1024 * 1024


@dataclass
class Detection:
    record: dict
    xml: bytes | None = None
    info: InvoiceXmlInfo | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_einvoice(self) -> bool:
        return self.xml is not None


def _xmp_standard(namespace: str | None) -> str | None:
    if not namespace:
        return None
    return XMP_NAMESPACE_STANDARD.get(namespace.split(":")[1])


def _candidates(attachments: list[Attachment], max_xml: int) -> list[tuple[Attachment, bytes, InvoiceXmlInfo]]:
    """Every attached XML whose root element is an invoice syntax we know."""
    found = []
    for att in attachments:
        if not att.name.lower().endswith(".xml") and att.name not in KNOWN_NAMES:
            continue
        try:
            data = att.read(max_xml)
            info = inspect_xml(data)
        except (ValueError, etree.XMLSyntaxError, pikepdf.PdfError):
            continue
        if info.syntax != "unknown":
            found.append((att, data, info))
    return found


def _rank(att: Attachment, xmp_filename: str | None) -> tuple:
    if xmp_filename and att.name == xmp_filename:
        return (0, 0)
    if att.name in KNOWN_NAMES:
        return (1, list(KNOWN_NAMES).index(att.name))
    lowered = {k.lower(): i for i, k in enumerate(KNOWN_NAMES)}
    if att.name.lower() in lowered:
        return (2, lowered[att.name.lower()])
    return (3, 0)


def detect(pdf: pikepdf.Pdf, max_xml_bytes: int = DEFAULT_MAX_XML_BYTES) -> Detection:
    attachments = find_attachments(pdf)
    xmp = parse_xmp(read_xmp(pdf))
    xmp_inv = xmp["einvoice"]
    xmp_filename = xmp_inv.get("DocumentFileName")
    warnings: list[str] = []

    candidates = sorted(_candidates(attachments, max_xml_bytes), key=lambda c: _rank(c[0], xmp_filename))
    record: dict = {
        "einvoice": False,
        "standard": None,
        "profile": None,
        "xrechnung_version": None,
        "en16931_compliant": False,
        "syntax": None,
        "document": None,
        "urn": None,
        "xml": None,
        "xmp": {"namespace": xmp["einvoice_namespace"], **xmp_inv} if xmp_inv else None,
        "pdfa": xmp["pdfa"] or None,
        "attachments": [a.name for a in attachments],
        "warnings": warnings,
    }
    if not candidates:
        if xmp_inv:
            warnings.append("XMP declares an e-invoice but no invoice XML is attached")
        return Detection(record, warnings=warnings)

    att, data, info = candidates[0]
    if len(candidates) > 1:
        warnings.append("several invoice XMLs attached: " + ", ".join(c[0].name for c in candidates)
                        + f"; using {att.name}")

    standard = _xmp_standard(xmp["einvoice_namespace"]) or KNOWN_NAMES.get(att.name)
    if info.syntax == "UBL":
        standard = "UBL invoice attached to PDF (not ZUGFeRD/Factur-X)"
    record.update({
        "einvoice": True,
        "standard": standard,
        "profile": info.profile,
        "xrechnung_version": info.xrechnung_version,
        "xrechnung_extension": info.xrechnung_extension or None,
        "en16931_compliant": info.en16931_compliant,
        "syntax": info.syntax,
        "document": info.document,
        "urn": info.urn,
        "xml": {
            "name": att.name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "afrelationship": att.afrelationship,
            "mime_type": att.mime_type,
            "sources": att.sources,
        },
    })

    # --- consistency checks between the signals ---
    if att.name not in KNOWN_NAMES:
        lowered = {k.lower(): k for k in KNOWN_NAMES}
        if att.name.lower() in lowered:
            warnings.append(f"attachment name {att.name!r} differs in case from {lowered[att.name.lower()]!r}")
        else:
            warnings.append(f"non-standard attachment name {att.name!r}")
    if att.name == "ZUGFeRD-invoice.xml" and info.syntax == "CII":
        warnings.append("ZUGFeRD 1.0 file name but ZUGFeRD 2.x/Factur-X (CII D16B) content")
    if att.name != "ZUGFeRD-invoice.xml" and info.syntax == "ZUGFeRD1":
        warnings.append("ZUGFeRD 1.0 content under a ZUGFeRD 2.x/Factur-X file name")
    if info.syntax == "UBL" and att.name in KNOWN_NAMES:
        warnings.append(f"{att.name} must contain CII, but contains UBL")
    if info.profile == "UNKNOWN":
        warnings.append(f"unrecognised specification identifier {info.urn!r}")
    if att.name == "xrechnung.xml" and info.profile != "XRECHNUNG":
        warnings.append(f"xrechnung.xml contains profile {info.profile}, not XRECHNUNG")

    if not xmp_inv:
        warnings.append("no ZUGFeRD/Factur-X metadata in XMP")
    else:
        level = normalise_xmp_level(xmp_inv.get("ConformanceLevel"))
        if level and level != info.profile:
            warnings.append(f"XMP ConformanceLevel {xmp_inv.get('ConformanceLevel')!r} "
                            f"but the XML declares {info.profile}")
        if xmp_filename and xmp_filename != att.name:
            warnings.append(f"XMP DocumentFileName {xmp_filename!r} but the XML is attached as {att.name!r}")

    if att.afrelationship is None:
        warnings.append("embedded XML has no AFRelationship")
    elif att.afrelationship not in VALID_RELATIONSHIPS:
        warnings.append(f"AFRelationship {att.afrelationship!r} is not Alternative, Data or Source")
    if "catalog_af" not in att.sources:
        warnings.append("embedded XML is not listed in the document's /AF array")

    part = xmp["pdfa"].get("part")
    if part != "3":
        warnings.append(f"not PDF/A-3 (XMP pdfaid:part is {part!r})" if part else "no PDF/A identification in XMP")

    return Detection(record, xml=data, info=info, warnings=warnings)
