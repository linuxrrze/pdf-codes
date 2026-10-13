"""Embed a CII invoice XML into a PDF to make a ZUGFeRD / Factur-X (PDF/A-3) file.

What is written:
- the XML as an embedded file with MIME type, AFRelationship and dates, in the EmbeddedFiles name tree
  and the catalog's /AF array;
- XMP metadata: pdfaid part 3, the Factur-X properties (fx:DocumentType, DocumentFileName, Version,
  ConformanceLevel) and the PDF/A extension schema that declares them; Info dictionary values are
  synchronised into XMP;
- an sRGB output intent if the PDF has none.

What is not done here: making the page content PDF/A compliant (embedded fonts, colour spaces).
If the input is not PDF/A already, the caller gets a warning and can pre-convert with Ghostscript.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

import pikepdf
from lxml import etree
from PIL import ImageCms

from ..core.attachments import find_attachments
from ..core.output import ToolError
from ..core.xmlsafe import parse_xml
from ..core.xmp import EINVOICE_NS, PDFAID_NS, parse_xmp, read_xmp
from .profiles import InvoiceXmlInfo, inspect_xml

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "pdfaid": PDFAID_NS,
    "fx": "urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#",
    "pdfaExtension": "http://www.aiim.org/pdfa/ns/extension/",
    "pdfaSchema": "http://www.aiim.org/pdfa/ns/schema#",
    "pdfaProperty": "http://www.aiim.org/pdfa/ns/property#",
}
XMP_CONFORMANCE = {
    "MINIMUM": "MINIMUM",
    "BASIC WL": "BASIC WL",
    "BASIC": "BASIC",
    "EN16931": "EN 16931",
    "EXTENDED": "EXTENDED",
    "XRECHNUNG": "XRECHNUNG",
}
XSD_LEVEL = {
    "MINIMUM": "minimum",
    "BASIC WL": "basicwl",
    "BASIC": "basic",
    "EN16931": "en16931",
    "EXTENDED": "extended",
}
RELATIONSHIPS = ("Alternative", "Data", "Source", "Supplement", "Unspecified")
FX_PROPERTIES = (
    ("DocumentFileName", "The name of the embedded XML document"),
    ("DocumentType", "The type of the hybrid document in capital letters, e.g. INVOICE or ORDER"),
    ("Version", "The actual version of the standard applying to the embedded XML document"),
    ("ConformanceLevel", "The conformance level of the embedded XML document"),
)
EMPTY_XMP = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
             b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>'
             b'</x:xmpmeta><?xpacket end="w"?>')


@dataclass
class EmbedResult:
    pdf: bytes
    info: InvoiceXmlInfo
    attachment_name: str
    warnings: list[str] = field(default_factory=list)


def check_invoice_xml(xml: bytes, check_xsd: bool = True) -> InvoiceXmlInfo:
    try:
        info = inspect_xml(xml)
    except etree.XMLSyntaxError as exc:
        raise ToolError(f"invoice XML is not well-formed: {exc}") from exc
    if info.syntax == "UBL":
        raise ToolError("the XML is UBL; ZUGFeRD/Factur-X can only embed CII "
                        "(XRechnung in CII syntax, e.g. *_uncefact.xml)")
    if info.syntax == "ZUGFeRD1":
        raise ToolError("ZUGFeRD 1.0 XML is not supported; embed a ZUGFeRD 2.x / Factur-X / XRechnung CII")
    if info.syntax != "CII":
        raise ToolError("the XML is not a CII invoice (root element is not rsm:CrossIndustryInvoice)")
    if info.profile not in XMP_CONFORMANCE:
        raise ToolError(f"unrecognised specification identifier (BT-24) {info.urn!r}")
    if check_xsd:
        level = XSD_LEVEL.get(info.profile) or ("extended" if info.xrechnung_extension else "en16931")
        _check_xsd(xml, level)
    return info


def _check_xsd(xml: bytes, level: str) -> None:
    import facturx  # deferred: importing it configures logging and loads schemas

    logging.getLogger("factur-x").setLevel(logging.ERROR)
    try:
        facturx.xml_check_xsd(xml, flavor="factur-x", level=level)
    except Exception as exc:  # factur-x raises plain Exception on schema errors
        raise ToolError(f"XML fails the Factur-X {level} XML schema: {exc}") from exc


def _pdf_date(when: dt.datetime) -> str:
    return when.strftime("D:%Y%m%d%H%M%SZ")


def _srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _ensure_output_intent(pdf: pikepdf.Pdf) -> None:
    intents = pdf.Root.get("/OutputIntents")
    if isinstance(intents, pikepdf.Array):
        for intent in intents:
            if isinstance(intent, pikepdf.Dictionary) and intent.get("/S") == pikepdf.Name.GTS_PDFA1:
                return
    icc = pikepdf.Stream(pdf, _srgb_profile())
    icc.N = 3
    intent = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.OutputIntent,
        S=pikepdf.Name.GTS_PDFA1,
        OutputConditionIdentifier=pikepdf.String("sRGB"),
        RegistryName=pikepdf.String("http://www.color.org"),
        Info=pikepdf.String("sRGB IEC61966-2.1"),
        DestOutputProfile=pdf.make_indirect(icc),
    ))
    if isinstance(intents, pikepdf.Array):
        intents.append(intent)
    else:
        pdf.Root.OutputIntents = pikepdf.Array([intent])


def _remove_attachment(pdf: pikepdf.Pdf, name: str) -> None:
    for att in find_attachments(pdf):
        if att.name != name:
            continue
        if name in pdf.attachments:
            del pdf.attachments[name]
        af = pdf.Root.get("/AF")
        if isinstance(af, pikepdf.Array):
            keep = [x for x in af if not (x.is_indirect and att.filespec.is_indirect and x.objgen == att.filespec.objgen)]
            pdf.Root.AF = pikepdf.Array(keep)


DC_CONTAINERS = {"date": "Seq", "creator": "Seq", "title": "Alt", "description": "Alt", "rights": "Alt",
                 "subject": "Bag"}


def _repair_dublin_core(rdf: etree._Element) -> None:
    """Wrap plain-text Dublin Core values in the RDF containers the XMP spec (and PDF/A) require.

    Older producers write e.g. ``<dc:date>2016-01-19</dc:date>`` instead of an rdf:Seq.
    """
    dc = "http://purl.org/dc/elements/1.1/"
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"
    for el in rdf.iter(f"{{{dc}}}*"):
        container = DC_CONTAINERS.get(etree.QName(el).localname)
        if container is None or len(el) or not (el.text or "").strip():
            continue
        value, el.text = el.text.strip(), None
        holder = etree.SubElement(el, f"{{{NS['rdf']}}}{container}")
        li = etree.SubElement(holder, f"{{{NS['rdf']}}}li")
        li.text = value
        if container == "Alt":
            li.set(xml_lang, "x-default")


def _rewrite_xmp(raw: bytes, conformance_letter: str, attachment_name: str, level: str) -> bytes:
    root = parse_xml(raw or EMPTY_XMP)
    rdf = root if etree.QName(root).localname == "RDF" else root.find(".//rdf:RDF", NS)
    if rdf is None:
        raise ToolError("XMP metadata has no rdf:RDF element")

    # Drop every existing PDF/A identification and e-invoice property, plus their extension schemas,
    # so the result has exactly one consistent set.
    def is_ours(ns: str | None) -> bool:
        return bool(ns) and (ns == PDFAID_NS or EINVOICE_NS.match(ns) is not None)

    for desc in rdf.findall("rdf:Description", NS):
        for attr in list(desc.attrib):
            if is_ours(etree.QName(attr).namespace):
                del desc.attrib[attr]
        for child in list(desc):
            if is_ours(etree.QName(child).namespace):
                desc.remove(child)
    for li in rdf.findall(".//pdfaExtension:schemas/rdf:Bag/rdf:li", NS):
        uri = li.findtext("pdfaSchema:namespaceURI", default="", namespaces=NS)
        if is_ours(uri.strip()):
            li.getparent().remove(li)

    _repair_dublin_core(rdf)

    def description(nsmap: dict) -> etree._Element:
        return etree.SubElement(rdf, f"{{{NS['rdf']}}}Description", {f"{{{NS['rdf']}}}about": ""}, nsmap=nsmap)

    def prop(parent: etree._Element, ns: str, local: str, text: str) -> etree._Element:
        el = etree.SubElement(parent, f"{{{NS[ns]}}}{local}")
        el.text = text
        return el

    pdfa = description({"pdfaid": NS["pdfaid"]})
    prop(pdfa, "pdfaid", "part", "3")
    prop(pdfa, "pdfaid", "conformance", conformance_letter)

    fx = description({"fx": NS["fx"]})
    prop(fx, "fx", "DocumentType", "INVOICE")
    prop(fx, "fx", "DocumentFileName", attachment_name)
    prop(fx, "fx", "Version", "1.0")
    prop(fx, "fx", "ConformanceLevel", level)

    bag = rdf.find(".//pdfaExtension:schemas/rdf:Bag", NS)
    if bag is None:
        ext = description({k: NS[k] for k in ("pdfaExtension", "pdfaSchema", "pdfaProperty")})
        schemas = etree.SubElement(ext, f"{{{NS['pdfaExtension']}}}schemas")
        bag = etree.SubElement(schemas, f"{{{NS['rdf']}}}Bag")
    li = etree.SubElement(bag, f"{{{NS['rdf']}}}li", {f"{{{NS['rdf']}}}parseType": "Resource"})
    prop(li, "pdfaSchema", "schema", "Factur-X PDFA Extension Schema")
    prop(li, "pdfaSchema", "namespaceURI", NS["fx"])
    prop(li, "pdfaSchema", "prefix", "fx")
    seq = etree.SubElement(etree.SubElement(li, f"{{{NS['pdfaSchema']}}}property"), f"{{{NS['rdf']}}}Seq")
    for name, desc_text in FX_PROPERTIES:
        p = etree.SubElement(seq, f"{{{NS['rdf']}}}li", {f"{{{NS['rdf']}}}parseType": "Resource"})
        prop(p, "pdfaProperty", "name", name)
        prop(p, "pdfaProperty", "valueType", "Text")
        prop(p, "pdfaProperty", "category", "external")
        prop(p, "pdfaProperty", "description", desc_text)

    xmp_root = root if etree.QName(root).localname == "xmpmeta" else rdf.getparent()
    body = etree.tostring(xmp_root, encoding="utf-8")
    return (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + body
            + b"\n" + b" " * 2048 + b'\n<?xpacket end="w"?>')


def pdfa_convert(pdf: bytes) -> bytes:
    """Rewrite a PDF with Ghostscript so that all fonts are embedded and colours are RGB.

    Verified with Ghostscript 10.08 + veraPDF: the result of pdfa_convert() followed by embed() passes PDF/A-3b.
    """
    gs = shutil.which("gs")
    if not gs:
        raise ToolError("--pdfa-convert needs Ghostscript (gs), which was not found")
    with tempfile.TemporaryDirectory(prefix="code-tools-gs-") as tmp:
        src, dst = f"{tmp}/in.pdf", f"{tmp}/out.pdf"
        with open(src, "wb") as fh:
            fh.write(pdf)
        # PDF/A mode makes Ghostscript write font data PDF/A accepts (e.g. no partial CIDSet); the output
        # intent and XMP it lacks are added by embed() afterwards.
        cmd = [gs, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
               "-dPDFA=3", "-dPDFACompatibilityPolicy=1", "-dEmbedAllFonts=true", "-dSubsetFonts=true",
               "-sColorConversionStrategy=RGB", f"-sOutputFile={dst}", src]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        if proc.returncode != 0:
            raise ToolError(f"Ghostscript failed: {(proc.stderr or proc.stdout).strip()[-500:]}")
        with open(dst, "rb") as fh:
            return fh.read()


def embed(pdf_data: bytes, xml: bytes, *, relationship: str = "Alternative", attachment_name: str = "factur-x.xml",
          check_xsd: bool = True, replace: bool = False, convert: bool = False, image_only: bool = False,
          now: dt.datetime | None = None) -> EmbedResult:
    if relationship not in RELATIONSHIPS:
        raise ToolError(f"AFRelationship must be one of {', '.join(RELATIONSHIPS)}")
    info = check_invoice_xml(xml, check_xsd)
    warnings: list[str] = []
    now = now or dt.datetime.now(dt.UTC)

    if convert:
        pdf_data = pdfa_convert(pdf_data)
    try:
        pdf = pikepdf.open(io.BytesIO(pdf_data))
    except pikepdf.PdfError as exc:
        raise ToolError(f"unreadable PDF: {exc}") from exc

    with pdf:
        if pdf.is_encrypted:
            raise ToolError("encrypted PDFs cannot be PDF/A; decrypt first")
        existing = parse_xmp(read_xmp(pdf))
        part = existing["pdfa"].get("part")
        letter = existing["pdfa"].get("conformance", "B").upper()
        if letter not in ("A", "B", "U"):
            letter = "B"
        # A PDF made from images has no fonts and only DeviceGray/DeviceRGB images, so its content is fine for
        # PDF/A once the output intent and metadata below are added.
        if part is None and not convert and not image_only:
            warnings.append("input is not PDF/A: the output carries PDF/A-3 metadata, but fonts and colours "
                            "are unchanged and may not comply (use --pdfa-convert, or create PDF/A-3 upstream)")

        names = {a.name for a in find_attachments(pdf)}
        if attachment_name in names:
            if not replace:
                raise ToolError(f"the PDF already contains {attachment_name} (use --replace)")
            _remove_attachment(pdf, attachment_name)
        invoice_names = {"factur-x.xml", "xrechnung.xml", "zugferd-invoice.xml", "ZUGFeRD-invoice.xml"}
        others = sorted((names & invoice_names) - {attachment_name})
        if others:
            warnings.append(f"the PDF also contains {', '.join(others)}; consumers may pick either")

        spec = pikepdf.AttachedFileSpec(
            pdf, xml,
            description="Factur-X/ZUGFeRD invoice",
            filename=attachment_name,
            mime_type="text/xml",
            creation_date=_pdf_date(now),
            mod_date=_pdf_date(now),
            relationship=pikepdf.Name("/" + relationship),
        )
        pdf.attachments[attachment_name] = spec
        filespec = pdf.attachments[attachment_name].obj
        if not filespec.is_indirect:
            filespec = pdf.make_indirect(filespec)
        # Recent pikepdf versions list new attachments in /AF themselves; make sure it is there exactly once.
        af = pdf.Root.get("/AF")
        if not isinstance(af, pikepdf.Array):
            pdf.Root.AF = pikepdf.Array([filespec])
        elif not any(x.is_indirect and x.objgen == filespec.objgen for x in af):
            af.append(filespec)

        _ensure_output_intent(pdf)

        # Synchronise Info → XMP (PDF/A requires them to agree), then add our properties.
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=True) as meta:
            meta.load_from_docinfo(pdf.docinfo, delete_missing=False)
        xmp = _rewrite_xmp(read_xmp(pdf) or b"", letter, attachment_name, XMP_CONFORMANCE[info.profile])
        stream = pikepdf.Stream(pdf, xmp)
        stream.Type = pikepdf.Name.Metadata
        stream.Subtype = pikepdf.Name.XML
        pdf.Root.Metadata = pdf.make_indirect(stream)

        out = io.BytesIO()
        pdf.save(out, min_version="1.7")
    return EmbedResult(out.getvalue(), info, attachment_name, warnings)
