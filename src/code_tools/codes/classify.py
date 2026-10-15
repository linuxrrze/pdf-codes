"""Classify a barcode payload: the first parser whose header matches decides the type.

Each parser checks a distinctive header and then validates the structure. A parser that recognises its
header always claims the payload, reporting ``valid: false`` plus ``errors`` if the structure is broken, so a
damaged payment code is still reported as one. Payloads no parser recognises are ``raw``.

A parser that crashes is a bug, but it must not abort the scan of a whole document. Its payload is reported as
``raw`` with ``valid: false`` and an error naming the parser. Later parsers are not tried: a crash may come
after the parser recognised its format, and a looser parser such as ``url`` would then misreport the payload.
"""

from __future__ import annotations

from collections.abc import Callable

from .parsers import (bcbp, beihilfe, dhl, emvco, epc, erezept, generic, gs1, icao_vds, iso15434, kassensichv, kbv,
                      otpauth, rksv, swiss_qr, uic)

Parser = Callable[[bytes, str | None], dict | None]

PARSERS: list[tuple[str, Parser]] = [
    ("epc", epc.match),
    ("swiss_qr", swiss_qr.match),
    ("emvco_mpm", emvco.match),
    ("gs1", gs1.match),
    ("iso15434", iso15434.match),
    ("uic_ticket", uic.match),
    ("icao_vds", icao_vds.match),
    ("eu_dcc", generic.eu_dcc),
    ("medication_plan", generic.medication_plan),
    ("deutsche_post_franking", generic.deutsche_post_franking),
    ("pkv_invoice_code", generic.pkv_invoice_code),
    ("erezept", erezept.match),
    ("kbv_form", kbv.match),
    ("iata_bcbp", bcbp.match),
    ("kassensichv_receipt", kassensichv.match),
    ("rksv_receipt", rksv.match),
    ("dhl_return_label", dhl.match),
    ("beihilfe_form", beihilfe.match),
    ("vcard", generic.vcard),
    ("icalendar", generic.icalendar),
    ("mecard", generic.mecard),
    ("wifi", generic.wifi),
    ("otpauth", otpauth.match),
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
    for name, parser in PARSERS:
        try:
            result = parser(data, aim)
            if result is not None:
                return {"type": result["type"], "valid": result.get("valid", True),
                        "errors": result.get("errors", []), "warnings": result.get("warnings", []), **result}
        except Exception as exc:  # a parser bug must not abort the scan
            return {"type": "raw", "valid": False,
                    "errors": [f"internal error in the {name} parser: {type(exc).__name__}: {exc}"],
                    "warnings": []}
    return {"type": "raw", "valid": True, "errors": [], "warnings": []}
