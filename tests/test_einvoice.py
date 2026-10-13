from __future__ import annotations

import io
import shutil

import pikepdf
import pytest
from conftest import CORPUS, TESTSUITE
from pdfgen import PdfBuilder, matrix_image, qr_matrix

from pdfsieve.cli import einvoice_info, pdf_attachments, xrechnung2zugferd, zugferd2xrechnung
from pdfsieve.core.attachments import safe_filename
from pdfsieve.einvoice.profiles import profile_from_urn

XR_CII = TESTSUITE / "standard" / "01.01a-INVOICE_uncefact.xml"
XR_UBL = TESTSUITE / "standard" / "01.01a-INVOICE_ubl.xml"
PDFA3 = CORPUS / "XML-Rechnung/FX/EN16931_Einfach.pdf"
PLAIN = CORPUS / "unstructured/RE-E-974-Hetzner_2016-01-19_R0005532486.pdf"


@pytest.mark.parametrize("urn, profile, version", [
    ("urn:factur-x.eu:1p0:minimum", "MINIMUM", None),
    ("urn:zugferd.de:2p0:minimum", "MINIMUM", None),
    ("urn:factur-x.eu:1p0:basicwl", "BASIC WL", None),
    ("urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic", "BASIC", None),
    ("urn:cen.eu:en16931:2017#compliant#urn:zugferd.de:2p0:basic", "BASIC", None),
    ("urn:cen.eu:en16931:2017", "EN16931", None),
    ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended", "EXTENDED", None),
    ("urn:cen.eu:en16931:2017:compliant:factur-x.eu:1p0:extended", "EXTENDED", None),
    ("urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.1", "XRECHNUNG", "2.1"),
    ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", "XRECHNUNG", "3.0"),
    ("urn:ferd:CrossIndustryDocument:invoice:1p0:comfort", "COMFORT", None),
    ("urn:something:else", "UNKNOWN", None),
    (None, "UNKNOWN", None),
])
def test_profile_from_urn(urn, profile, version):
    assert profile_from_urn(urn)[:2] == (profile, version)


def test_xrechnung_extension_flag():
    urn = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0"
    assert profile_from_urn(urn) == ("XRECHNUNG", "3.0", True)


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\evil\\x.xml") == "x.xml"
    assert safe_filename("..") == "attachment"
    assert safe_filename("factur-x.xml") == "factur-x.xml"


CORPUS_EXPECTED = [
    ("ZUGFeRDv1/correct/Intarsys/ZUGFeRD_1p0_BASIC_Einfach.pdf", "ZUGFeRD 1.0", "BASIC", False),
    ("ZUGFeRDv1/correct/Intarsys/ZUGFeRD_1p0_COMFORT_Einfach.pdf", "ZUGFeRD 1.0", "COMFORT", False),
    ("ZUGFeRDv2/correct/intarsys/MINIMUM/zugferd_2p0_MINIMUM.pdf", "ZUGFeRD 2.0", "MINIMUM", False),
    ("ZUGFeRDv2/correct/intarsys/EN16931/zugferd_2p0_EN16931_Einfach.pdf", "ZUGFeRD 2.0", "EN16931", True),
    ("ZUGFeRDv2/correct/intarsys/EXTENDED/zugferd_2p0_EXTENDED_Warenrechnung.pdf", "ZUGFeRD 2.0", "EXTENDED", True),
    ("ZUGFeRDv2/correct/symtrax/Beispiele/BASIC WL/zugferd_2p1_BASIC-WL_Einfach.pdf", "Factur-X / ZUGFeRD 2.1+",
     "BASIC WL", False),
    ("ZUGFeRDv2/correct/symtrax/Beispiele/BASIC/zugferd_2p1_BASIC_Einfach.pdf", "Factur-X / ZUGFeRD 2.1+", "BASIC",
     True),
    ("XML-Rechnung/FX/EN16931_Einfach.pdf", "Factur-X / ZUGFeRD 2.1+", "EN16931", True),
    ("XML-Rechnung/FX/XRECHNUNG_Einfach.pdf", "Factur-X / ZUGFeRD 2.1+", "XRECHNUNG", True),
]


@pytest.mark.corpus
@pytest.mark.parametrize("rel, standard, profile, compliant", CORPUS_EXPECTED)
def test_corpus_detection(invoke, rel, standard, profile, compliant):
    r = invoke(einvoice_info.main, CORPUS / rel)
    assert r.code == 0
    rec = r.records[0]
    assert (rec["standard"], rec["profile"], rec["en16931_compliant"]) == (standard, profile, compliant)
    assert rec["warnings"] == []


@pytest.mark.corpus
@pytest.mark.parametrize("rel, warning", [
    ("ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf", "non-standard attachment name"),
    ("ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf", "must contain CII, but contains UBL"),
    ("ZUGFeRDv2/fail/MustangRE-20171118_506_ZUGFeRD1and2.pdf", "several invoice XMLs"),
    ("ZUGFeRDv2/correct/symtrax/Beispiele/EN16931/zugferd_2p1_EN16931_Elektron_XRechnung.pdf",
     "XMP ConformanceLevel 'EN 16931' but the XML declares XRECHNUNG"),
])
def test_corpus_inconsistencies_are_reported(invoke, rel, warning):
    rec = invoke(einvoice_info.main, CORPUS / rel).records[0]
    assert any(warning in w for w in rec["warnings"]), rec["warnings"]
    assert invoke(einvoice_info.main, "--warnings-fail", CORPUS / rel).code == 1


@pytest.mark.corpus
def test_non_einvoice_and_filters(invoke):
    r = invoke(einvoice_info.main, PLAIN)
    assert r.code == 1 and r.records[0]["einvoice"] is False
    minimum = CORPUS / "ZUGFeRDv2/correct/intarsys/MINIMUM/zugferd_2p0_MINIMUM.pdf"
    assert invoke(einvoice_info.main, "-q", minimum).code == 0
    assert invoke(einvoice_info.main, "-q", "--strict", minimum).code == 1
    assert invoke(einvoice_info.main, "-q", "--require-xrechnung", PDFA3).code == 1
    # grep semantics over several files: 0 if any matches
    r = invoke(einvoice_info.main, PLAIN, PDFA3)
    assert r.code == 0 and [rec["einvoice"] for rec in r.records] == [False, True]


@pytest.mark.corpus
def test_extract(invoke, tmp_path):
    r = invoke(zugferd2xrechnung.main, CORPUS / "XML-Rechnung/FX/XRECHNUNG_Einfach.pdf")
    assert r.code == 0 and b"<rsm:CrossIndustryInvoice" in r.stdout
    out = tmp_path / "x.xml"
    assert invoke(zugferd2xrechnung.main, PDFA3, "-o", out).code == 0
    assert invoke(zugferd2xrechnung.main, PDFA3, "-o", out).code == 2  # exists, no --force
    assert invoke(zugferd2xrechnung.main, "--require-xrechnung", PDFA3).code == 1
    minimum = CORPUS / "ZUGFeRDv2/correct/intarsys/MINIMUM/zugferd_2p0_MINIMUM.pdf"
    r = invoke(zugferd2xrechnung.main, minimum)
    assert r.code == 0 and "not a complete EN 16931 invoice" in r.stderr
    assert invoke(zugferd2xrechnung.main, "--strict", minimum).code == 1
    assert invoke(zugferd2xrechnung.main, PLAIN).code == 1
    ubl_pdf = CORPUS / "ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf"
    assert invoke(zugferd2xrechnung.main, ubl_pdf).code == 2  # UBL needs --syntax ubl


@pytest.mark.corpus
def test_attachments(invoke, tmp_path):
    pdf = CORPUS / "XML-Rechnung/FX/XRECHNUNG_Elektron.pdf"
    r = invoke(pdf_attachments.main, pdf)
    assert r.code == 0
    names = {rec["name"]: rec for rec in r.records}
    assert set(names) == {"EN16931_Elektron_Aufmass.png", "EN16931_Elektron_ElektronRapport.pdf", "xrechnung.xml"}
    assert names["xrechnung.xml"]["afrelationship"] == "Source"
    r = invoke(pdf_attachments.main, pdf, "-x", tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names)
    r = invoke(pdf_attachments.main, pdf, "--name", "xrechnung.xml")
    assert r.stdout.startswith(b"<?xml")
    assert invoke(pdf_attachments.main, PLAIN).code == 1


def _info(invoke, pdf_path):
    return invoke(einvoice_info.main, pdf_path).records[0]


@pytest.mark.corpus
def test_round_trip_into_plain_pdf(invoke, tmp_path):
    out = tmp_path / "zugferd.pdf"
    r = invoke(xrechnung2zugferd.main, PLAIN, XR_CII, "-o", out)
    assert r.code == 0
    assert "input is not PDF/A" in r.stderr
    rec = _info(invoke, out)
    assert (rec["profile"], rec["xrechnung_version"], rec["xml"]["name"]) == ("XRECHNUNG", "3.0", "factur-x.xml")
    assert rec["xml"]["afrelationship"] == "Alternative"
    assert rec["xmp"]["ConformanceLevel"] == "XRECHNUNG"
    assert rec["pdfa"] == {"part": "3", "conformance": "B"}
    assert rec["warnings"] == []
    assert invoke(zugferd2xrechnung.main, out).stdout == XR_CII.read_bytes()
    with pikepdf.open(out) as pdf:
        assert pdf.pdf_version == "1.7"
        assert "/OutputIntents" in pdf.Root
        assert "/Filter" not in pdf.Root.Metadata  # PDF/A wants readable XMP


@pytest.mark.corpus
def test_replace_existing_invoice(invoke, tmp_path):
    out = tmp_path / "replaced.pdf"
    assert invoke(xrechnung2zugferd.main, PDFA3, XR_CII, "-o", out).code == 2  # already has factur-x.xml
    r = invoke(xrechnung2zugferd.main, "--replace", "--require-pdfa", PDFA3, XR_CII, "-o", out)
    assert r.code == 0 and r.stderr == ""
    rec = _info(invoke, out)
    assert rec["profile"] == "XRECHNUNG" and rec["warnings"] == []
    assert rec["attachments"] == ["factur-x.xml"]


@pytest.mark.corpus
def test_embed_rejections(invoke, tmp_path):
    out = tmp_path / "o.pdf"
    assert invoke(xrechnung2zugferd.main, PLAIN, XR_UBL, "-o", out).code == 2
    assert invoke(xrechnung2zugferd.main, PLAIN, XR_CII, "-o", PLAIN).code == 2  # never overwrite input
    assert invoke(xrechnung2zugferd.main, "--require-pdfa", PLAIN, XR_CII, "-o", out).code == 2
    bad = tmp_path / "bad.xml"
    bad.write_bytes(XR_CII.read_bytes().replace(b"<rsm:ExchangedDocument>", b"<rsm:Unexpected/><rsm:ExchangedDocument>"))
    r = invoke(xrechnung2zugferd.main, PLAIN, bad, "-o", out)
    assert r.code == 2 and "XML schema" in r.stderr
    assert not out.exists()


@pytest.mark.corpus
@pytest.mark.skipif(shutil.which("gs") is None, reason="needs Ghostscript")
def test_pdfa_convert(invoke, tmp_path):
    out = tmp_path / "converted.pdf"
    r = invoke(xrechnung2zugferd.main, "--pdfa-convert", PLAIN, XR_CII, "-o", out)
    assert r.code == 0 and r.stderr == ""  # no "input is not PDF/A" warning
    rec = _info(invoke, out)
    assert rec["profile"] == "XRECHNUNG" and rec["warnings"] == []
    assert invoke(zugferd2xrechnung.main, out).stdout == XR_CII.read_bytes()


def test_embed_into_generated_pdf_with_qr(invoke, tmp_path):
    """No corpus needed: a generated PDF plus a minimal valid CII still round-trips."""
    b = PdfBuilder()
    b.add_image(b.page(), matrix_image(qr_matrix("hello")), 50, 50, 60, 60)
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b.build())
    xml = tmp_path / "inv.xml"
    xml.write_bytes(MINIMAL_CII)
    out = tmp_path / "out.pdf"
    assert invoke(xrechnung2zugferd.main, pdf, xml, "-o", out).code == 0
    rec = _info(invoke, out)
    assert rec["profile"] == "MINIMUM" and rec["xmp"]["ConformanceLevel"] == "MINIMUM"
    with pikepdf.open(io.BytesIO(out.read_bytes())) as p:
        assert [str(x.get("/AFRelationship")) for x in p.Root.AF] == ["/Alternative"]


MINIMAL_CII = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
 xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:factur-x.eu:1p0:minimum</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>INV-1</ram:ID><ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">20261013</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Seller GmbH</ram:Name>
        <ram:PostalTradeAddress><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE123456789</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Buyer AG</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>100.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">19.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>119.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
