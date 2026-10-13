"""Image input: code-scan on PNG/JPEG/TIFF/..., and xrechnung2zugferd with a scanned invoice."""

from __future__ import annotations

import io

import pikepdf
import pytest
from PIL import Image

from pdfgen import matrix_image, qr_matrix
from code_tools.cli import einvoice_info, code_scan, xrechnung2zugferd
from code_tools.codes.scan import ScanOptions, scan_image
from code_tools.core.imageio import Frame, images_to_pdf, open_frames
from test_einvoice import MINIMAL_CII


def page_with(code: Image.Image, at=(300, 400), size=(1240, 1754), mode="L") -> Image.Image:
    """A 150 dpi A4 page with ``code`` pasted at ``at`` (pixels)."""
    page = Image.new(mode, size, "white")
    page.paste(code.convert(mode), at)
    return page


def encode(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


@pytest.mark.parametrize("fmt, mode, kw", [
    ("PNG", "L", {"dpi": (150, 150)}),
    ("JPEG", "RGB", {"quality": 85}),
    ("TIFF", "L", {"compression": "tiff_lzw"}),
    ("WEBP", "RGB", {"lossless": True}),
    ("BMP", "RGB", {}),
    ("GIF", "L", {}),
])
def test_formats(invoke, tmp_path, fmt, mode, kw):
    path = tmp_path / f"page.{fmt.lower()}"
    path.write_bytes(encode(page_with(matrix_image(qr_matrix("hello image"), 4), mode=mode), fmt, **kw))
    r = invoke(code_scan.main, path)
    assert r.code == 0, r.stderr
    (rec,) = r.records
    assert (rec["input"], rec["page"], rec["text"]) == ("image", 1, "hello image")
    assert "bbox_pt" not in rec and "outside_cropbox" not in rec
    # Pixels, origin top left. The code was pasted at (300, 400) with 4 px per module and a 4-module quiet zone.
    side = len(qr_matrix("hello image")) * 4
    assert rec["bbox_px"] == pytest.approx([316, 416, 300 + side - 16, 400 + side - 16], abs=3)


def test_multi_page_tiff_and_pages_option(invoke, tmp_path):
    blank = Image.new("L", (600, 800), "white")
    with_code = page_with(matrix_image(qr_matrix("on page two"), 4), at=(100, 100), size=(600, 800))
    path = tmp_path / "scan.tif"
    blank.save(path, save_all=True, append_images=[with_code, blank], compression="tiff_lzw")
    r = invoke(code_scan.main, path)
    assert [(rec["page"], rec["text"]) for rec in r.records] == [(2, "on page two")]
    assert invoke(code_scan.main, "--pages", "1,3", path).code == 1


def test_exif_rotation_transparency_and_16bit(invoke, tmp_path):
    code = matrix_image(qr_matrix("exif"), 4)
    upright = page_with(code, at=(50, 50), size=(400, 300), mode="RGB")
    rotated = upright.rotate(90, expand=True)
    exif = Image.Exif()
    exif[0x0112] = 6  # stored rotated; viewers turn it upright
    jpeg = tmp_path / "photo.jpg"
    jpeg.write_bytes(encode(rotated, "JPEG", quality=90, exif=exif))
    (rec,) = invoke(code_scan.main, jpeg).records
    assert rec["text"] == "exif"
    assert rec["bbox_px"][0] < 200 and rec["bbox_px"][1] < 200  # coordinates in the upright image

    rgba = Image.new("RGBA", (400, 400), (0, 0, 0, 0))  # transparent background must become white
    rgba.paste(Image.merge("RGBA", (code, code, code, Image.new("L", code.size, 255))), (40, 40))
    png = tmp_path / "transparent.png"
    rgba.save(png)
    assert invoke(code_scan.main, png).records[0]["text"] == "exif"

    deep = page_with(code, at=(20, 20), size=(300, 300)).convert("I;16").point(lambda v: v * 256)
    png16 = tmp_path / "deep.png"
    deep.save(png16)
    assert invoke(code_scan.main, png16).records[0]["text"] == "exif"


def test_small_code_in_large_image_is_found():
    m = qr_matrix("tiny image code")
    n = len(m)
    code = Image.new("L", (n, n), 255)
    code.putdata([0 if dark else 255 for row in m for dark in row])
    code = code.resize((round(n * 1.6), round(n * 1.6)), Image.BILINEAR)  # ~1.6 pixels per module
    hits = scan_image(Frame(page_with(code, at=(1200, 1700), size=(2480, 3508)), 300.0), 1, ScanOptions())
    assert [h.text for h in hits] == ["tiny image code"]


def test_stdin_errors_and_limits(invoke, tmp_path):
    data = encode(page_with(matrix_image(qr_matrix("from stdin"), 4)), "PNG")
    r = invoke(code_scan.main, "--fast", "-", stdin=data)
    assert [(rec["file"], rec["text"]) for rec in r.records] == [("<stdin>", "from stdin")]
    junk = tmp_path / "x.png"
    junk.write_bytes(b"not an image at all")
    r = invoke(code_scan.main, junk)
    assert r.code == 2 and "neither a PDF nor a readable image" in r.stderr
    r = invoke(code_scan.main, "--max-image-pixels", "1000", "-", stdin=data)
    assert r.code == 2 and "larger than 1000 pixels" in r.stderr


def test_images_to_pdf_page_size():
    frames = open_frames(encode(Image.new("RGB", (2480, 3508), "white"), "PNG", dpi=(300, 300)), "a4.png")
    with pikepdf.open(io.BytesIO(images_to_pdf(frames))) as pdf:
        assert [round(float(v)) for v in pdf.pages[0].MediaBox] == [0, 0, 595, 842]  # A4
    no_dpi = open_frames(encode(Image.new("L", (600, 300), "white"), "PNG"), "x.png")
    with pikepdf.open(io.BytesIO(images_to_pdf(no_dpi, default_dpi=72))) as pdf:
        assert [round(float(v)) for v in pdf.pages[0].MediaBox] == [0, 0, 600, 300]


def test_zugferd_from_scanned_invoice(invoke, tmp_path):
    scan = tmp_path / "scan.jpg"
    scan.write_bytes(encode(Image.new("RGB", (1240, 1754), "white"), "JPEG", dpi=(150, 150)))
    xml = tmp_path / "invoice.xml"
    xml.write_bytes(MINIMAL_CII)
    out = tmp_path / "zugferd.pdf"
    r = invoke(xrechnung2zugferd.main, "--require-pdfa", scan, xml, "-o", out)
    assert r.code == 0 and r.stderr == ""  # image-only content: no "input is not PDF/A" warning
    rec = invoke(einvoice_info.main, out).records[0]
    assert rec["profile"] == "MINIMUM" and rec["warnings"] == [] and rec["pdfa"]["part"] == "3"
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1 and "/OutputIntents" in pdf.Root
