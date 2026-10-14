"""Classify a barcode payload: the first parser whose header matches decides the type.

Each parser checks a distinctive header and then validates the structure. A parser that recognises its
header always claims the payload, reporting ``valid: false`` plus ``errors`` if the structure is broken, so a
damaged payment code is still reported as one. Payloads no parser recognises are ``raw``.
"""

from __future__ import annotations

from collections.abc import Callable

from .parsers import bcbp, beihilfe, dhl, epc, generic, gs1, kassensichv, kbv, swiss_qr, uic

Parser = Callable[[bytes, str | None], dict | None]

PARSERS: list[tuple[str, Parser]] = [
    ("epc", epc.match),
    ("swiss_qr", swiss_qr.match),
    ("gs1", gs1.match),
    ("uic_ticket", uic.match),
    ("eu_dcc", generic.eu_dcc),
    ("medication_plan", generic.medication_plan),
    ("deutsche_post_franking", generic.deutsche_post_franking),
    ("pkv_invoice_code", generic.pkv_invoice_code),
    ("kbv_form", kbv.match),
    ("iata_bcbp", bcbp.match),
    ("kassensichv_receipt", kassensichv.match),
    ("dhl_return_label", dhl.match),
    ("beihilfe_form", beihilfe.match),
    ("vcard", generic.vcard),
    ("mecard", generic.mecard),
    ("wifi", generic.wifi),
    ("mailto", generic.mailto),
    ("tel", generic.tel),
    ("sms", generic.sms),
    ("geo", generic.geo),
    ("url", generic.url),
]
TYPES = [name for name, _ in PARSERS] + ["raw"]


def classify(data: bytes, aim: str | None = None) -> dict:
    """``aim`` is the AIM symbology identifier reported by the decoder (e.g. ``]Q3`` for GS1 QR).

    Every result starts with ``type``, ``valid``, ``errors`` and ``warnings``, whether the parser set them or not.
    """
    for _name, parser in PARSERS:
        result = parser(data, aim)
        if result is not None:
            return {"type": result["type"], "valid": result.get("valid", True), "errors": result.get("errors", []),
                    "warnings": result.get("warnings", []), **result}
    return {"type": "raw", "valid": True, "errors": [], "warnings": []}
