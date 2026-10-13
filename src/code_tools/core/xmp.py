"""Read the parts of a PDF's XMP metadata that matter for e-invoices and PDF/A.

Producers write XMP properties either as elements or as attributes of rdf:Description, so both
forms are read. Only namespace URIs are matched, never prefixes.
"""

from __future__ import annotations

import re

import pikepdf
from lxml import etree

from .xmlsafe import parse_xml

PDFAID_NS = "http://www.aiim.org/pdfa/ns/id/"
# ZUGFeRD 1.0: urn:ferd:pdfa:CrossIndustryDocument:invoice:1p0#
# ZUGFeRD 2.0: urn:zugferd:pdfa:CrossIndustryDocument:invoice:2p0#
# Factur-X / ZUGFeRD 2.1+: urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#
EINVOICE_NS = re.compile(r"^urn:(ferd|zugferd|factur-x):pdfa:CrossIndustryDocument:invoice:\w+#$")
EINVOICE_FIELDS = ("DocumentType", "DocumentFileName", "Version", "ConformanceLevel")


def _local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ns, local
    return "", tag


def read_xmp(pdf: pikepdf.Pdf) -> bytes | None:
    meta = pdf.Root.get("/Metadata")
    if not isinstance(meta, pikepdf.Stream):
        return None
    try:
        return meta.read_bytes()
    except pikepdf.PdfError:
        return None


def parse_xmp(raw: bytes | None) -> dict:
    """Return ``{"pdfa": {...}, "einvoice": {...}, "einvoice_namespace": str|None}``."""
    result: dict = {"pdfa": {}, "einvoice": {}, "einvoice_namespace": None}
    if not raw:
        return result
    raw = raw.strip(b"\x00 \r\n\t")
    try:
        root = parse_xml(raw)
    except etree.XMLSyntaxError:
        result["error"] = "unparseable XMP"
        return result

    def take(ns: str, local: str, value: str | None):
        if value is None or not value.strip():
            return
        value = value.strip()
        if ns == PDFAID_NS and local in ("part", "conformance", "amd", "rev"):
            result["pdfa"].setdefault(local, value)
        elif EINVOICE_NS.match(ns) and local in EINVOICE_FIELDS:
            result["einvoice"].setdefault(local, value)
            result["einvoice_namespace"] = result["einvoice_namespace"] or ns

    for el in root.iter():
        if not isinstance(el.tag, str):
            continue  # comments, processing instructions
        ns, local = _local(el.tag)
        if len(el) == 0:
            take(ns, local, el.text)
        for attr, value in el.attrib.items():
            take(*_local(attr), value)
    return result
