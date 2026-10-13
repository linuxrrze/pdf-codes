from __future__ import annotations

import base64
import pathlib

import pypdfium2 as pdfium
import pytest
import zxingcpp
from pdfgen import A3, A4, MM, PdfBuilder, matrix_image, qr_matrix, zxing_image

from pdfsieve.cli import pdf_codes
from pdfsieve.codes.scan import ScanOptions, scan_page

TINY_MM = 2.5  # readable only by the tiled pass (verified: missed at 300 dpi)
EPC = b"BCD\n002\n1\nSCT\n\nWikimedia Foerdergesellschaft\nDE33100205000001194700\nEUR5\n\n\nSpende"
BINARY = b"\x00\x01\xffbinary\n\x00payload"


def inner_box(x, y, size, payload):
    """Expected bbox of the QR symbol itself (without its 4-module quiet zone)."""
    n = len(qr_matrix(payload))
    q = size * 4 / n
    return (x + q, y + q, x + size - q, y + size - q)


@pytest.fixture(scope="module")
def placement_pdf(tmp_path_factory):
    b = PdfBuilder()
    expected = {}  # (page, text) -> expected bbox or None (position not asserted exactly)

    p = b.page(A4)
    w, h = A4
    for name, (x, y) in {"corner-bl": (0, 0), "corner-br": (w - 60, 0), "corner-tl": (0, h - 60),
                         "corner-tr": (w - 60, h - 60), "margin-left": (2, h / 2)}.items():
        b.add_image(p, matrix_image(qr_matrix(name)), x, y, 60, 60)
        expected[(1, name)] = inner_box(x, y, 60, name)
    b.add_image(p, matrix_image(qr_matrix("rotated-37")), 250, 420, 70, 70, angle=37)
    expected[(1, "rotated-37")] = None
    b.add_image(p, matrix_image(qr_matrix("rotated-90")), 250, 300, 70, 70, angle=90)
    expected[(1, "rotated-90")] = inner_box(250, 300, 70, "rotated-90")
    b.add_rect(p, 90, 590, 120, 120, 0)
    b.add_image(p, matrix_image(qr_matrix("inverted"), invert=True), 100, 600, 100, 100)
    expected[(1, "inverted")] = inner_box(100, 600, 100, "inverted")
    b.add_vector_qr(p, qr_matrix("vector"), 400, 650, 80)
    expected[(1, "vector")] = inner_box(400, 650, 80, "vector")
    b.add_image_in_form(p, matrix_image(qr_matrix("in-form")), 300, 120, 60)
    expected[(1, "in-form")] = inner_box(300, 120, 60, "in-form")
    b.add_annotation_qr(p, matrix_image(qr_matrix("annotation")), 420, 300, 60)
    expected[(1, "annotation")] = inner_box(420, 300, 60, "annotation")
    b.add_image(p, zxing_image("CODE128-XYZ", zxingcpp.BarcodeFormat.Code128), 100, 200, 150, 40)
    expected[(1, "CODE128-XYZ")] = None
    b.add_image(p, zxing_image("DMTX-1", zxingcpp.BarcodeFormat.DataMatrix, scale=6), 200, 500, 40, 40)
    expected[(1, "DMTX-1")] = None

    p = b.page(A3)
    b.add_vector_qr(p, qr_matrix("tiny"), 400, 600, TINY_MM * MM)
    expected[(2, "tiny")] = inner_box(400, 600, TINY_MM * MM, "tiny")
    # Straddles the right edge of the first tile column (x = 510 pt with default settings).
    b.add_vector_qr(p, qr_matrix("tile-border"), 506, 900, TINY_MM * MM)
    expected[(2, "tile-border")] = inner_box(506, 900, TINY_MM * MM, "tile-border")

    p = b.page(A4)
    for x, y in ((50, 50), (400, 600)):
        b.add_image(p, matrix_image(qr_matrix("twice")), x, y, 60, 60)
    b.add_image(p, matrix_image(qr_matrix(EPC, error="m")), 200, 300, 90, 90)
    b.add_image(p, matrix_image(qr_matrix(BINARY)), 200, 500, 80, 80)

    p = b.page(A4, cropbox=[0, 0, 400, 600])
    b.add_image(p, matrix_image(qr_matrix("outside-crop")), 450, 700, 80, 80)
    b.add_image(p, matrix_image(qr_matrix("inside-crop")), 50, 50, 80, 80)

    p = b.page(A4, rotate=90)
    b.add_image(p, matrix_image(qr_matrix("rotated-page")), 100, 150, 80, 80)
    expected[(5, "rotated-page")] = inner_box(100, 150, 80, "rotated-page")

    path = tmp_path_factory.mktemp("codes") / "placement.pdf"
    path.write_bytes(b.build())
    return path, expected


def _scan(path, **opts):
    doc = pdfium.PdfDocument(str(path))
    try:
        return [hit for i in range(len(doc)) for hit in scan_page(doc, i, ScanOptions(**opts))]
    finally:
        doc.close()


@pytest.fixture(scope="module")
def default_hits(placement_pdf):
    return _scan(placement_pdf[0])


@pytest.fixture(scope="module")
def fast_hits(placement_pdf):
    return _scan(placement_pdf[0], tiles=False, images=False)


def test_every_placement_found_once(placement_pdf, default_hits):
    _, expected = placement_pdf
    for (page, text), box in expected.items():
        hits = [h for h in default_hits if h.page == page and h.text == text]
        assert len(hits) == 1, f"{text!r} on page {page}: {len(hits)} hits"
        if box is not None:
            assert hits[0].bbox == pytest.approx(box, abs=3), text


def test_identical_codes_in_different_places_stay_separate(default_hits):
    twice = [h for h in default_hits if h.text == "twice"]
    assert len(twice) == 2
    assert twice[0].bbox != pytest.approx(twice[1].bbox, abs=10)


def test_tiny_code_needs_tile_pass(fast_hits, default_hits):
    assert not [h for h in fast_hits if h.text == "tiny"]
    tiny = [h for h in default_hits if h.text == "tiny"]
    assert tiny and "tile" in tiny[0].sources


def test_sources_are_merged(default_hits):
    corner = next(h for h in default_hits if h.text == "corner-bl")
    assert {"render", "tile", "image"} <= set(corner.sources)
    vector = next(h for h in default_hits if h.text == "vector")
    assert "image" not in vector.sources  # vector graphics have no image object


def test_cropbox_flag(default_hits):
    flags = {h.text: h.outside_cropbox for h in default_hits if h.page == 4}
    assert flags == {"outside-crop": True, "inside-crop": False}


def test_symbologies(default_hits):
    by_text = {h.text: h for h in default_hits}
    assert by_text["CODE128-XYZ"].symbology == "Code128"
    assert by_text["DMTX-1"].symbology == "DataMatrix"
    assert by_text["vector"].symbology == "QRCode"


def test_cli_json_and_payloads(invoke, placement_pdf):
    r = invoke(pdf_codes.main, "--pages", "3", placement_pdf[0])
    assert r.code == 0
    recs = r.records
    epc = next(rec for rec in recs if rec["payload"]["type"] == "epc")
    assert epc["payload"]["valid"] and epc["payload"]["amount"] == "5.00"
    assert base64.b64decode(epc["bytes_b64"]) == EPC
    binary = next(rec for rec in recs if base64.b64decode(rec["bytes_b64"]) == BINARY)
    assert binary["payload"]["type"] == "raw"
    assert sorted(rec["page"] for rec in recs) == [3, 3, 3, 3]


def test_cli_raw_is_exact(invoke, placement_pdf):
    r = invoke(pdf_codes.main, "--raw", "-0", "--pages", "3", placement_pdf[0])
    assert r.code == 0
    # Exact bytes, each followed by NUL; the binary payload contains NULs itself, which is reported.
    assert sorted(r.stdout.replace(BINARY + b"\0", b"").split(b"\0")[:-1]) == sorted([b"twice", b"twice", EPC])
    assert BINARY + b"\0" in r.stdout
    assert "contains a NUL" in r.stderr
    r = invoke(pdf_codes.main, "--raw", "--pages", "3", "--symbology", "qr", placement_pdf[0])
    assert "contains a newline" in r.stderr  # the multi-line EPC payload without -0
    r = invoke(pdf_codes.main, "--raw", "--symbology", "datamatrix", "--pages", "1", placement_pdf[0])
    assert r.stdout == b"DMTX-1\n"


def test_cli_symbology_filter_and_exit_codes(invoke, placement_pdf, tmp_path):
    r = invoke(pdf_codes.main, "-q", "--fast", "--pages", "2", placement_pdf[0])
    assert r.code == 1 and r.stdout == b""  # tiny codes only, invisible to --fast
    r = invoke(pdf_codes.main, "--symbology", "code128", "--pages", "1", placement_pdf[0])
    assert [rec["text"] for rec in r.records] == ["CODE128-XYZ"]
    assert invoke(pdf_codes.main, "--symbology", "nonsense", placement_pdf[0]).code == 2
    assert invoke(pdf_codes.main, tmp_path / "missing.pdf").code == 2
    notpdf = tmp_path / "x.pdf"
    notpdf.write_text("hello")
    assert invoke(pdf_codes.main, notpdf).code == 2


def test_cli_save(invoke, placement_pdf, tmp_path):
    r = invoke(pdf_codes.main, "--pages", "3", "--save", tmp_path / "out", placement_pdf[0])
    saved = {rec["saved_to"] for rec in r.records}
    assert len(saved) == 4
    contents = sorted(pathlib.Path(p).read_bytes() for p in saved)
    assert contents == sorted([b"twice", b"twice", EPC, BINARY])
    assert any(p.endswith(".bin") for p in saved)


def test_cli_stdin(invoke, placement_pdf):
    r = invoke(pdf_codes.main, "--fast", "--pages", "5", "-", stdin=placement_pdf[0].read_bytes())
    assert [(rec["file"], rec["text"]) for rec in r.records] == [("<stdin>", "rotated-page")]
