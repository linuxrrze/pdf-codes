"""Reading raster images (PNG, JPEG, TIFF, GIF, WebP, BMP, ... whatever Pillow supports) as page-like frames,
and wrapping images in a minimal PDF."""

from __future__ import annotations

import io
from dataclasses import dataclass

import pikepdf
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from .output import ToolError

DEFAULT_DPI = 300.0
DEFAULT_MAX_IMAGE_PIXELS = 200_000_000


@dataclass
class Frame:
    image: Image.Image  # grayscale or RGB, EXIF orientation applied, transparency flattened onto white
    dpi: float | None   # from the file's metadata, if it states one


def _normalise(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, rgba)
    if img.mode in ("1", "L"):
        return img.convert("L") if img.mode == "1" else img
    if img.mode.startswith("I") or img.mode == "F":  # 16/32-bit grayscale: scale to 8 bits
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    return img.convert("RGB")


def _dpi(img: Image.Image) -> float | None:
    dpi = img.info.get("dpi")
    try:
        value = float(dpi[0]) if dpi else None
    except (TypeError, ValueError, IndexError):
        return None
    return value if value and value > 1 else None


def open_frames(data: bytes, name: str, max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS) -> list[Frame]:
    """All frames of an image (pages of a multi-page TIFF, frames of a GIF), ready for decoding."""
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        img = Image.open(io.BytesIO(data))
        frames = []
        for frame in ImageSequence.Iterator(img):
            frame = ImageOps.exif_transpose(frame)
            frames.append(Frame(_normalise(frame), _dpi(frame) or _dpi(img)))
        return frames
    except Image.DecompressionBombError as exc:
        raise ToolError(f"{name}: image larger than {max_pixels} pixels") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ToolError(f"{name}: neither a PDF nor a readable image ({exc})") from exc


def images_to_pdf(frames: list[Frame], default_dpi: float = DEFAULT_DPI) -> bytes:
    """One PDF page per frame, sized from the image's resolution. Images are stored losslessly (Flate)
    as DeviceGray or DeviceRGB, which is PDF/A compatible once an output intent is added."""
    pdf = pikepdf.new()
    for frame in frames:
        img = frame.image
        dpi = frame.dpi or default_dpi
        w_pt, h_pt = img.size[0] * 72 / dpi, img.size[1] * 72 / dpi
        stream = pikepdf.Stream(pdf, img.tobytes())  # pikepdf compresses with Flate on save
        stream.Type = pikepdf.Name.XObject
        stream.Subtype = pikepdf.Name.Image
        stream.Width, stream.Height = img.size
        stream.ColorSpace = pikepdf.Name.DeviceGray if img.mode == "L" else pikepdf.Name.DeviceRGB
        stream.BitsPerComponent = 8
        content = pikepdf.Stream(pdf, f"q {w_pt:.4f} 0 0 {h_pt:.4f} 0 0 cm /Im0 Do Q".encode())
        page = pikepdf.Dictionary(
            Type=pikepdf.Name.Page,
            MediaBox=pikepdf.Array([0, 0, w_pt, h_pt]),
            Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=stream)),
            Contents=content,
        )
        pdf.pages.append(pikepdf.Page(page))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()
