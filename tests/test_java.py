"""Tests that run the real KoSIT validator and CII→UBL converter (Java). Skipped without them."""

from __future__ import annotations

import pytest
from conftest import CORPUS, TESTSUITE

from code_tools.cli import einvoice_validate, xrechnung2zugferd, zugferd2xrechnung
from code_tools.core.xmlsafe import parse_xml

pytestmark = [pytest.mark.java, pytest.mark.corpus]

XR_CII = TESTSUITE / "standard" / "01.01a-INVOICE_uncefact.xml"
XR_UBL = TESTSUITE / "standard" / "01.01a-INVOICE_ubl.xml"
PLAIN = CORPUS / "unstructured/RE-E-974-Hetzner_2016-01-19_R0005532486.pdf"


def test_valid_xml_both_syntaxes(invoke):
    r = invoke(einvoice_validate.main, XR_CII, XR_UBL)
    assert r.code == 0, r.stderr
    assert [rec["valid"] for rec in r.records] == [True, True]
    assert "XRechnung" in r.records[0]["scenario"]


def test_invalid_xml_reports_rule(invoke, tmp_path):
    bad = tmp_path / "bad.xml"
    data = XR_CII.read_bytes()
    start = data.index(b"<ram:BuyerReference>")
    end = data.index(b"</ram:BuyerReference>") + len(b"</ram:BuyerReference>")
    bad.write_bytes(data[:start] + data[end:])
    r = invoke(einvoice_validate.main, bad)
    assert r.code == 1
    rec = r.records[0]
    assert not rec["valid"]
    assert "BR-DE-15" in {e["code"] for e in rec["errors"]}


def test_validate_pdf_after_embedding(invoke, tmp_path):
    out = tmp_path / "z.pdf"
    assert invoke(xrechnung2zugferd.main, "-q", PLAIN, XR_CII, "-o", out).code == 0
    r = invoke(einvoice_validate.main, "--report-dir", tmp_path / "reports", out)
    assert r.code == 0
    assert r.records[0]["source"] == "pdf:factur-x.xml"
    assert (tmp_path / "reports" / "1" / "kosit-report.xml").exists()


def test_extract_as_ubl_validates(invoke, tmp_path):
    pdf = tmp_path / "z.pdf"
    assert invoke(xrechnung2zugferd.main, "-q", PLAIN, XR_CII, "-o", pdf).code == 0
    ubl = tmp_path / "x-ubl.xml"
    assert invoke(zugferd2xrechnung.main, "--syntax", "ubl", pdf, "-o", ubl).code == 0
    root = parse_xml(ubl.read_bytes())
    assert root.tag == "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
    customization = root.findtext("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID")
    assert customization == "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
    r = invoke(einvoice_validate.main, ubl)
    assert r.code == 0 and r.records[0]["valid"], r.records


@pytest.mark.slow
@pytest.mark.parametrize("name", ["01.05a", "01.13a", "02.01a", "03.01a", "03.07a"])
def test_conversion_of_test_suite_cases(invoke, tmp_path, name):
    """Cases the pure-Python converter could not handle (multiple payment means, order references, ...)."""
    src = next((TESTSUITE / "standard").glob(f"{name}-INVOICE_uncefact.xml"))
    pdf = tmp_path / "z.pdf"
    assert invoke(xrechnung2zugferd.main, "-q", PLAIN, src, "-o", pdf).code == 0
    ubl = tmp_path / "u.xml"
    assert invoke(zugferd2xrechnung.main, "-q", "--syntax", "ubl", pdf, "-o", ubl).code == 0
    r = invoke(einvoice_validate.main, ubl)
    assert r.records[0]["valid"], r.records[0]["errors"]
