"""Build test PDFs with barcodes placed in every way a real PDF can contain them."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import pikepdf
import segno
import zxingcpp
from PIL import Image

MM = 72 / 25.4
A4 = (595.276, 841.89)
A3 = (841.89, 1190.55)


def qr_matrix(payload: str | bytes, error: str = "m") -> list[list[bool]]:
    """QR modules including a 4-module quiet zone."""
    qr = segno.make(payload, error=error, micro=False)
    return [[bool(v) for v in row] for row in qr.matrix_iter(scale=1, border=4)]


def matrix_image(matrix: list[list[bool]], px_per_module: int = 4, invert: bool = False) -> Image.Image:
    n_rows, n_cols = len(matrix), len(matrix[0])
    img = Image.new("L", (n_cols, n_rows), 255)
    img.putdata([(255 if dark else 0) if invert else (0 if dark else 255) for row in matrix for dark in row])
    return img.resize((n_cols * px_per_module, n_rows * px_per_module), Image.NEAREST)


def zxing_image(content: str, fmt: zxingcpp.BarcodeFormat, scale: int = 3, **kwargs) -> Image.Image:
    zimg = zxingcpp.create_barcode(content, fmt, **kwargs).to_image(scale=scale)
    h, w = zimg.shape
    img = Image.frombytes("L", (w, h), bytes(memoryview(zimg)))
    # Add a quiet zone.
    pad = 10 * scale
    out = Image.new("L", (w + 2 * pad, h + 2 * pad), 255)
    out.paste(img, (pad, pad))
    return out


EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111",
         "0001011"]
EAN_G = ["".join("1" if c == "0" else "0" for c in code)[::-1] for code in EAN_L]


def ean_add_on_modules(digits: str) -> str:
    """Bars of a 2- or 5-digit EAN add-on (GS1 General Specifications 5.2.3.4), 1 = dark module."""
    if len(digits) == 2:
        parity = ["LL", "LG", "GL", "GG"][int(digits) % 4]
    else:
        check = (3 * sum(int(d) for d in digits[::2]) + 9 * sum(int(d) for d in digits[1::2])) % 10
        parity = ["GGLLL", "GLGLL", "GLLGL", "GLLLG", "LGGLL", "LLGGL", "LLLGG", "LGLGL", "LGLLG", "LLGLG"][check]
    bars = "1011"
    for i, (d, p) in enumerate(zip(digits, parity)):
        bars += ("01" if i else "") + (EAN_L if p == "L" else EAN_G)[int(d)]
    return bars


def ean13_with_add_on(ean: str, add_on: str, scale: int = 3) -> Image.Image:
    main = zxing_image(ean, zxingcpp.BarcodeFormat.EAN13, scale=scale)
    bars = ean_add_on_modules(add_on)
    pad = 10 * scale  # zxing_image's quiet zone
    last_bar = max(x for x in range(main.size[0]) if main.getpixel((x, main.size[1] // 2)) < 128)
    x0 = last_bar + 1 + 9 * scale  # nine modules between the main symbol and the add-on
    out = Image.new("L", (x0 + (len(bars) + 10) * scale, main.size[1]), 255)
    out.paste(main, (0, 0))
    top = pad + (main.size[1] - 2 * pad) // 6  # add-on bars are shorter, leaving room for their digits
    for i, bar in enumerate(bars):
        if bar == "1":
            out.paste(0, (x0 + i * scale, top, x0 + (i + 1) * scale, main.size[1] - pad))
    return out


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def cm(a, b, c, d, e, f) -> str:
    return " ".join(_fmt(v) for v in (a, b, c, d, e, f)) + " cm"


def placement(x: float, y: float, w: float, h: float, angle_deg: float = 0) -> str:
    """Matrix that maps the unit square to a w×h box at (x, y), rotated about its centre."""
    t = math.radians(angle_deg)
    cos, sin = math.cos(t), math.sin(t)
    cx, cy = x + w / 2, y + h / 2
    # translate(centre) · rotate · scale · translate(-0.5, -0.5)
    a, b, c, d = w * cos, w * sin, -h * sin, h * cos
    e = cx - 0.5 * a - 0.5 * c
    f = cy - 0.5 * b - 0.5 * d
    return cm(a, b, c, d, e, f)


def vector_qr_ops(matrix: list[list[bool]], x: float, y: float, size: float) -> str:
    """Draw QR modules as filled rectangles (vector graphics, no image)."""
    n = len(matrix)
    m = size / n
    ops = ["q 0 g"]
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                ops.append(f"{_fmt(x + c * m)} {_fmt(y + (n - 1 - r) * m)} {_fmt(m)} {_fmt(m)} re")
    ops.append("f Q")
    return "\n".join(ops)


@dataclass
class PageSpec:
    size: tuple[float, float] = A4
    cropbox: tuple[float, float, float, float] | None = None
    rotate: int = 0
    ops: list[str] = field(default_factory=list)
    xobjects: dict[str, object] = field(default_factory=dict)
    annots: list[dict] = field(default_factory=list)


class PdfBuilder:
    def __init__(self):
        self.pdf = pikepdf.new()
        self.pages: list[PageSpec] = []
        self._n = 0

    def page(self, size=A4, cropbox=None, rotate=0) -> PageSpec:
        spec = PageSpec(size=size, cropbox=cropbox, rotate=rotate)
        self.pages.append(spec)
        return spec

    def _name(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def image_xobject(self, img: Image.Image) -> pikepdf.Stream:
        img = img.convert("L")
        stream = pikepdf.Stream(self.pdf, img.tobytes())
        stream.Type = pikepdf.Name.XObject
        stream.Subtype = pikepdf.Name.Image
        stream.Width, stream.Height = img.size
        stream.ColorSpace = pikepdf.Name.DeviceGray
        stream.BitsPerComponent = 8
        return stream

    def add_image(self, page: PageSpec, img: Image.Image, x, y, w, h, angle=0) -> None:
        name = self._name("Im")
        page.xobjects[name] = self.image_xobject(img)
        page.ops.append(f"q {placement(x, y, w, h, angle)} /{name} Do Q")

    def add_vector_qr(self, page: PageSpec, matrix, x, y, size) -> None:
        page.ops.append(vector_qr_ops(matrix, x, y, size))

    def add_rect(self, page: PageSpec, x, y, w, h, gray: float) -> None:
        page.ops.append(f"q {gray} g {x} {y} {w} {h} re f Q")

    def _form(self, ops: str, bbox, resources: dict) -> pikepdf.Stream:
        form = pikepdf.Stream(self.pdf, ops.encode())
        form.Type = pikepdf.Name.XObject
        form.Subtype = pikepdf.Name.Form
        form.BBox = pikepdf.Array(bbox)
        form.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary({"/" + k: v for k, v in resources.items()}))
        return form

    def add_image_in_form(self, page: PageSpec, img: Image.Image, x, y, size) -> None:
        """Image inside a form XObject, inside another form, each with its own matrix."""
        im_name = self._name("Im")
        inner = self._form(f"q {size} 0 0 {size} 0 0 cm /{im_name} Do Q", [0, 0, size, size],
                           {im_name: self.image_xobject(img)})
        inner.Matrix = pikepdf.Array([1, 0, 0, 1, 5, 7])  # an extra offset inside the outer form
        outer_name, inner_name = self._name("Fm"), self._name("Fm")
        outer = self._form(f"q 1 0 0 1 -5 -7 cm /{inner_name} Do Q", [-10, -10, size + 10, size + 10],
                           {inner_name: inner})
        page.xobjects[outer_name] = outer
        page.ops.append(f"q 1 0 0 1 {x} {y} cm /{outer_name} Do Q")

    def add_annotation_qr(self, page: PageSpec, img: Image.Image, x, y, size) -> None:
        """QR code that exists only in an annotation's appearance stream."""
        im_name = self._name("Im")
        ap = self._form(f"q {size} 0 0 {size} 0 0 cm /{im_name} Do Q", [0, 0, size, size],
                        {im_name: self.image_xobject(img)})
        page.annots.append(dict(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Stamp,
                                Rect=pikepdf.Array([x, y, x + size, y + size]), F=4,
                                AP=pikepdf.Dictionary(N=ap)))

    def build(self) -> bytes:
        for spec in self.pages:
            page = pikepdf.Dictionary(
                Type=pikepdf.Name.Page,
                MediaBox=pikepdf.Array([0, 0, *spec.size]),
                Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary({"/" + k: v for k, v in spec.xobjects.items()})),
                Contents=pikepdf.Stream(self.pdf, "\n".join(spec.ops).encode()),
            )
            if spec.cropbox:
                page.CropBox = pikepdf.Array(spec.cropbox)
            if spec.rotate:
                page.Rotate = spec.rotate
            if spec.annots:
                page.Annots = pikepdf.Array([self.pdf.make_indirect(pikepdf.Dictionary(**a)) for a in spec.annots])
            self.pdf.pages.append(pikepdf.Page(page))
        out = io.BytesIO()
        self.pdf.save(out)
        return out.getvalue()
