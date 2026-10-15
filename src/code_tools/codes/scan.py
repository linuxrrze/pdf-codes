"""Find and decode barcodes anywhere on PDF pages or in raster images.

Passes (see ``ScanOptions``):
1. full page rendered at ``dpi`` (annotations and form fields included);
2. overlapping tiles rendered at ``tile_dpi``, so small codes get enough pixels; the overlap is at least
   ``max_code_mm`` so every code up to that size lies completely inside some tile;
3. every embedded raster image at its native resolution, including images nested in form XObjects;
4. with ``thorough``: a 1200 dpi tile pass and alternative binarisers for faded scans.

EAN/UPC add-ons (two digits on periodicals, five on books) are read when present and appended to the main code's
digits, with AIM identifier ]E3. zxing-cpp then also reports the code without its add-on; that duplicate is
dropped when the two overlap.

Pages are rendered over the full MediaBox with page rotation removed, so pixel coordinates map linearly to PDF
user space. Hits from all passes are merged when they have the same symbology and bytes and overlapping boxes.

Raster images (``scan_image``) get the same treatment in pixel space: a pass at native resolution, then
overlapping tiles upscaled to ``tile_dpi`` (relative to the image's own resolution, or ``dpi`` when the file
does not state one). Their boxes are in pixels, origin top left.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import zxingcpp
from PIL import Image

from ..core.imageio import Frame

MM = 72 / 25.4
SOURCE_PRIORITY = {"image": 0, "tile-1200": 1, "tile": 2, "render": 3}
MAX_UPSCALE = 4  # lower = more precise position


@dataclass
class ScanOptions:
    dpi: float = 300
    tile_dpi: float = 600
    max_code_mm: float = 60
    tiles: bool = True
    images: bool = True
    thorough: bool = False
    formats: zxingcpp.BarcodeFormats | None = None
    max_pixels: int = 40_000_000  # per rendered bitmap


@dataclass
class Hit:
    page: int  # 1-based
    symbology: str
    aim: str
    content_type: str
    text: str
    data: bytes
    bbox: tuple[float, float, float, float]  # PDF user space (x0, y0, x1, y1), or pixels for images
    sources: list[str] = field(default_factory=list)
    outside_cropbox: bool = False


@dataclass
class _Affine:
    """Maps bitmap pixel coordinates to PDF user space."""
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f


def parse_formats(spec: str | None) -> zxingcpp.BarcodeFormats | None:
    if not spec:
        return None
    aliases = {"qr": "QRCode", "microqr": "MicroQRCode", "rmqr": "RMQRCode", "dm": "DataMatrix",
               "datamatrix": "DataMatrix", "aztec": "Aztec", "pdf417": "PDF417", "code128": "Code128",
               "code39": "Code39", "code93": "Code93", "ean13": "EAN13", "ean8": "EAN8", "upca": "UPCA",
               "upce": "UPCE", "itf": "ITF", "codabar": "Codabar", "databar": "DataBar", "maxicode": "MaxiCode",
               "linear": "AllLinear", "matrix": "AllMatrix"}
    names = [aliases.get(p.strip().lower().replace("-", "").replace("_", ""), p.strip())
             for p in spec.split(",") if p.strip()]
    try:
        return zxingcpp.barcode_formats_from_str(",".join(names))
    except Exception as exc:  # zxingcpp raises ValueError or RuntimeError depending on version
        raise ValueError(f"unknown symbology in {spec!r}: {exc}") from exc


def _decode(img: Image.Image, opts: ScanOptions, binarizer=None) -> list:
    kwargs = {"try_rotate": True, "try_invert": True, "try_downscale": True,
              "ean_add_on_symbol": zxingcpp.EanAddOnSymbol.Read}
    if opts.formats is not None:
        kwargs["formats"] = opts.formats
    if binarizer is not None:
        kwargs["binarizer"] = binarizer
    return zxingcpp.read_barcodes(img, **kwargs)


def _to_hit(code, affine: _Affine, page_no: int, source: str) -> Hit:
    pos = code.position
    pts = [affine.apply(p.x, p.y) for p in (pos.top_left, pos.top_right, pos.bottom_right, pos.bottom_left)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return Hit(page=page_no, symbology=code.format.name if hasattr(code.format, "name") else str(code.format),
               aim=code.symbology_identifier, content_type=str(code.content_type).split(".")[-1],
               text=code.text, data=bytes(code.bytes), bbox=(min(xs), min(ys), max(xs), max(ys)),
               sources=[source])


def _render(page: pdfium.PdfPage, box: tuple[float, float, float, float], region: tuple[float, float, float, float],
            dpi: float, max_pixels: int) -> tuple[Image.Image, _Affine]:
    """Render ``region`` (x0, y0, x1, y1 in user space, inside ``box``) to a grayscale image."""
    bx0, by0, bx1, by1 = box
    rx0, ry0, rx1, ry1 = region
    scale = dpi / 72
    pixels = (rx1 - rx0) * (ry1 - ry0) * scale * scale
    if pixels > max_pixels:
        scale *= math.sqrt(max_pixels / pixels)
    crop = (rx0 - bx0, ry0 - by0, bx1 - rx1, by1 - ry1)
    bitmap = page.render(scale=scale, crop=crop, grayscale=True, may_draw_forms=True, draw_annots=True,
                         fill_color=(255, 255, 255, 255))
    img = bitmap.to_pil().convert("L")
    # Pixel (0, 0) is the region's top-left corner; y grows downwards.
    return img, _Affine(1 / scale, 0, 0, -1 / scale, rx0, ry1)


def _tiles(box: tuple[float, float, float, float], tile: float, overlap: float) -> Iterator[tuple]:
    x0, y0, x1, y1 = box
    step = max(tile - overlap, 1.0)

    def starts(lo: float, hi: float) -> list[float]:
        if hi - lo <= tile:
            return [lo]
        out = [lo + i * step for i in range(math.ceil((hi - lo - tile) / step) + 1)]
        out[-1] = hi - tile  # last tile flush with the edge
        return out

    for ty in starts(y0, y1):
        for tx in starts(x0, x1):
            yield (tx, ty, min(tx + tile, x1), min(ty + tile, y1))


def _matrix(obj) -> _Affine:
    m = obj.get_matrix()
    return _Affine(m.a, m.b, m.c, m.d, m.e, m.f)


def _compose(inner: _Affine, outer: _Affine) -> _Affine:
    """inner applied first, then outer (PDF row-vector convention: inner × outer)."""
    return _Affine(
        inner.a * outer.a + inner.b * outer.c,
        inner.a * outer.b + inner.b * outer.d,
        inner.c * outer.a + inner.d * outer.c,
        inner.c * outer.b + inner.d * outer.d,
        inner.e * outer.a + inner.f * outer.c + outer.e,
        inner.e * outer.b + inner.f * outer.d + outer.f,
    )


def _iter_images(page: pdfium.PdfPage, form=None, ctm: _Affine | None = None, depth: int = 0):
    """Yield (image object, image→page matrix), recursing into form XObjects with their matrices."""
    ctm = ctm or _Affine(1, 0, 0, 1, 0, 0)
    if depth > 15:
        return
    for obj in page.get_objects(max_depth=0, form=form):
        if obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            yield obj, _compose(_matrix(obj), ctm)
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            yield from _iter_images(page, obj, _compose(_matrix(obj), ctm), depth + 1)


def _image_pass(page: pdfium.PdfPage, page_no: int, opts: ScanOptions) -> list[Hit]:
    hits = []
    for obj, to_page in _iter_images(page):
        try:
            img = obj.get_bitmap(render=False).to_pil()
        except Exception:  # unsupported filter or colour space: the render passes still see it
            continue
        if min(img.size) < 16 or img.size[0] * img.size[1] > opts.max_pixels:
            continue
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        w, h = img.size
        # Image space is the unit square with y up; pixel row 0 is the top of the image.
        affine = _compose(_Affine(1 / w, 0, 0, -1 / h, 0, 1), to_page)
        hits += [_to_hit(code, affine, page_no, "image") for code in _decode(img, opts)]
    return hits


def _overlaps(a, b, tol: float = 2.0) -> bool:
    return a[0] - tol <= b[2] and b[0] - tol <= a[2] and a[1] - tol <= b[3] and b[1] - tol <= a[3]


def merge_hits(hits: list[Hit]) -> list[Hit]:
    merged: list[Hit] = []
    for hit in sorted(hits, key=lambda h: SOURCE_PRIORITY.get(h.sources[0], 9)):
        for kept in merged:
            if kept.symbology == hit.symbology and kept.data == hit.data and _overlaps(kept.bbox, hit.bbox):
                for s in hit.sources:
                    if s not in kept.sources:
                        kept.sources.append(s)
                break
        else:
            merged.append(hit)
    with_add_on = [h for h in merged if h.aim == "]E3"]
    return [h for h in merged
            if not (h.aim and h.aim.startswith("]E") and h.aim != "]E3"
                    and any(a.symbology == h.symbology and a.data.startswith(h.data) and _overlaps(a.bbox, h.bbox)
                            for a in with_add_on))]


def scan_page(doc: pdfium.PdfDocument, index: int, opts: ScanOptions) -> list[Hit]:
    page = doc[index]
    page_no = index + 1
    cropbox = page.get_cropbox()
    rotation = page.get_rotation()
    try:
        box = page.get_mediabox()
        # Render the whole MediaBox, unrotated, so codes outside the visible crop area are found too and
        # pixel coordinates map straight to user space. This only changes the in-memory copy.
        page.set_rotation(0)
        page.set_cropbox(*box)
        hits: list[Hit] = []

        img, affine = _render(page, box, box, opts.dpi, opts.max_pixels)
        hits += [_to_hit(c, affine, page_no, "render") for c in _decode(img, opts)]
        if opts.thorough:
            for binarizer in (zxingcpp.Binarizer.GlobalHistogram, zxingcpp.Binarizer.FixedThreshold):
                hits += [_to_hit(c, affine, page_no, "render") for c in _decode(img, opts, binarizer)]
        del img

        if opts.tiles:
            passes = [("tile", opts.tile_dpi)] + ([("tile-1200", 1200)] if opts.thorough else [])
            overlap = opts.max_code_mm * MM
            for source, dpi in passes:
                # Tile edge: three code sizes, but small enough to stay under the pixel budget.
                tile = min(3 * overlap, math.sqrt(opts.max_pixels) * 72 / dpi)
                tile = max(tile, overlap * 1.25)
                for region in _tiles(box, tile, overlap):
                    img, affine = _render(page, box, region, dpi, opts.max_pixels)
                    hits += [_to_hit(c, affine, page_no, source) for c in _decode(img, opts)]

        if opts.images:
            hits += _image_pass(page, page_no, opts)

        merged = merge_hits(hits)
        for hit in merged:
            cx, cy = (hit.bbox[0] + hit.bbox[2]) / 2, (hit.bbox[1] + hit.bbox[3]) / 2
            hit.outside_cropbox = not (cropbox[0] <= cx <= cropbox[2] and cropbox[1] <= cy <= cropbox[3])
        merged.sort(key=lambda h: (-h.bbox[3], h.bbox[0]))
        return merged
    finally:
        page.set_cropbox(*cropbox)
        page.set_rotation(rotation)
        page.close()


def scan_image(frame: Frame, frame_no: int, opts: ScanOptions) -> list[Hit]:
    """Scan one raster image (or one frame of a multi-page image). Boxes are in pixels, origin top left."""
    img = frame.image
    dpi = frame.dpi or opts.dpi
    identity = _Affine(1, 0, 0, 1, 0, 0)
    hits = [_to_hit(c, identity, frame_no, "image") for c in _decode(img, opts)]
    if opts.thorough:
        for binarizer in (zxingcpp.Binarizer.GlobalHistogram, zxingcpp.Binarizer.FixedThreshold):
            hits += [_to_hit(c, identity, frame_no, "image") for c in _decode(img, opts, binarizer)]

    if opts.tiles:
        passes = [("tile", opts.tile_dpi)] + ([("tile-1200", 1200)] if opts.thorough else [])
        overlap = opts.max_code_mm / 25.4 * dpi  # in source pixels
        for source, target_dpi in passes:
            factor = min(target_dpi / dpi, MAX_UPSCALE)
            if factor <= 1.05:
                continue  # the image is already at least that sharp; the native pass covered it
            tile = min(3 * overlap, math.sqrt(opts.max_pixels) / factor)
            tile = max(tile, overlap * 1.25)
            for x0, y0, x1, y1 in _tiles((0, 0, img.size[0], img.size[1]), tile, overlap):
                box = (int(x0), int(y0), math.ceil(x1), math.ceil(y1))
                part = img.crop(box)
                part = part.resize((round(part.size[0] * factor), round(part.size[1] * factor)), Image.BICUBIC)
                affine = _Affine(1 / factor, 0, 0, 1 / factor, box[0], box[1])
                hits += [_to_hit(c, affine, frame_no, source) for c in _decode(part, opts)]

    merged = merge_hits(hits)
    merged.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
    return merged
