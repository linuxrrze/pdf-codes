"""Recognise the syntax and profile of an invoice XML.

The profile comes from the specification identifier (BT-24): in CII it is
``ExchangedDocumentContext/GuidelineSpecifiedDocumentContextParameter/ID``, in UBL ``CustomizationID``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from lxml import etree

from ..core.xmlsafe import parse_xml

NS_CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_ZF1 = "urn:ferd:CrossIndustryDocument:invoice:1p0"
NS_UBL_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_UBL_CREDITNOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_RSM_RAM = {
    "rsm": NS_CII,
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}

# Profiles whose content is a complete invoice under EN 16931 (BASIC is a compliant subset).
EN16931_COMPLIANT = {"BASIC", "EN16931", "EXTENDED", "XRECHNUNG"}

# XMP ConformanceLevel spellings, normalised to profile names.
XMP_LEVELS = {
    "MINIMUM": "MINIMUM",
    "BASIC WL": "BASIC WL",
    "BASICWL": "BASIC WL",
    "BASIC": "BASIC",
    "COMFORT": "COMFORT",
    "EN 16931": "EN16931",
    "EN16931": "EN16931",
    "EXTENDED": "EXTENDED",
    "XRECHNUNG": "XRECHNUNG",
}

_XR_VERSION = re.compile(r"xrechnung_(\d+(?:\.\d+)*)")


@dataclass
class InvoiceXmlInfo:
    syntax: str  # "CII" | "ZUGFeRD1" | "UBL" | "unknown"
    document: str | None  # "Invoice" | "CreditNote" | "CrossIndustryInvoice" | ...
    urn: str | None
    profile: str  # MINIMUM, BASIC WL, BASIC, COMFORT, EN16931, EXTENDED, XRECHNUNG, UNKNOWN
    xrechnung_version: str | None
    xrechnung_extension: bool
    en16931_compliant: bool

    def as_dict(self) -> dict:
        return asdict(self)


def profile_from_urn(urn: str | None) -> tuple[str, str | None, bool]:
    """Map a specification identifier to ``(profile, xrechnung_version, is_xrechnung_extension)``.

    Rules rather than an exact table, because producers vary separators (``#`` vs ``:``) and the
    XRechnung URN changed from ``urn:xoev-de:kosit:standard:xrechnung_2.x`` to
    ``urn:xeinkauf.de:kosit:xrechnung_3.0``.
    """
    if not urn:
        return "UNKNOWN", None, False
    u = urn.strip().lower()
    if "xrechnung" in u:
        m = _XR_VERSION.search(u)
        return "XRECHNUNG", m.group(1) if m else None, "extension" in u
    for token, profile in ((":minimum", "MINIMUM"), (":basicwl", "BASIC WL"), (":basic", "BASIC"),
                           (":comfort", "COMFORT"), (":extended", "EXTENDED")):
        if u.endswith(token):
            return profile, None, False
    if u == "urn:cen.eu:en16931:2017" or u.endswith(":en16931"):
        return "EN16931", None, False
    return "UNKNOWN", None, False


def _first_text(root: etree._Element, xpath: str, ns: dict) -> str | None:
    hits = root.xpath(xpath, namespaces=ns)
    for hit in hits:
        text = hit if isinstance(hit, str) else hit.text
        if text and text.strip():
            return text.strip()
    return None


def inspect_xml(data: bytes) -> InvoiceXmlInfo:
    """Identify syntax and profile. Raises ``etree.XMLSyntaxError`` for malformed XML."""
    root = parse_xml(data)
    ns = etree.QName(root).namespace
    local = etree.QName(root).localname
    if ns == NS_CII:
        syntax = "CII"
        urn = _first_text(root, "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
                          NS_RSM_RAM)
    elif ns == NS_ZF1:
        syntax = "ZUGFeRD1"
        urn = _first_text(root, "*[local-name()='SpecifiedExchangedDocumentContext']"
                                "/*[local-name()='GuidelineSpecifiedDocumentContextParameter']"
                                "/*[local-name()='ID']", {})
    elif ns in (NS_UBL_INVOICE, NS_UBL_CREDITNOTE):
        syntax = "UBL"
        urn = _first_text(root, "*[local-name()='CustomizationID']", {})
    else:
        return InvoiceXmlInfo("unknown", local, None, "UNKNOWN", None, False, False)
    profile, xr_version, xr_ext = profile_from_urn(urn)
    return InvoiceXmlInfo(
        syntax=syntax,
        document=local,
        urn=urn,
        profile=profile,
        xrechnung_version=xr_version,
        xrechnung_extension=xr_ext,
        en16931_compliant=syntax != "ZUGFeRD1" and profile in EN16931_COMPLIANT,
    )


def normalise_xmp_level(level: str | None) -> str | None:
    if level is None:
        return None
    return XMP_LEVELS.get(" ".join(level.upper().split()), level)
