"""Reading inputs and opening PDFs, with limits for untrusted files."""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass

import pikepdf
import pypdfium2 as pdfium

from .output import ToolError

DEFAULT_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_PAGES = 2000


@dataclass
class Limits:
    max_bytes: int = DEFAULT_MAX_BYTES
    max_pages: int = DEFAULT_MAX_PAGES


def add_limit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, metavar="N",
                        help="refuse inputs larger than N bytes (default: %(default)s)")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES, metavar="N",
                        help="refuse PDFs with more than N pages (default: %(default)s)")


def limits_from_args(args: argparse.Namespace) -> Limits:
    return Limits(max_bytes=args.max_bytes, max_pages=args.max_pages)


def read_input(path: str, limits: Limits | None = None) -> bytes:
    """Read a file, or stdin when ``path`` is ``-``."""
    limits = limits or Limits()
    try:
        if path == "-":
            data = sys.stdin.buffer.read(limits.max_bytes + 1)
        else:
            with open(path, "rb") as fh:
                data = fh.read(limits.max_bytes + 1)
    except OSError as exc:
        raise ToolError(f"{path}: {exc.strerror or exc}") from exc
    if len(data) > limits.max_bytes:
        raise ToolError(f"{path}: larger than --max-bytes ({limits.max_bytes})")
    return data


def display_name(path: str) -> str:
    return "<stdin>" if path == "-" else path


def is_pdf(data: bytes) -> bool:
    # The header may be preceded by junk; PDF readers accept it within the first 1024 bytes.
    return b"%PDF-" in data[:1024]


def open_pikepdf(data: bytes, name: str) -> pikepdf.Pdf:
    if not is_pdf(data):
        raise ToolError(f"{name}: not a PDF")
    try:
        return pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError as exc:
        raise ToolError(f"{name}: encrypted PDF needs a password") from exc
    except pikepdf.PdfError as exc:
        raise ToolError(f"{name}: unreadable PDF: {exc}") from exc


def open_pdfium(data: bytes, name: str, limits: Limits | None = None) -> pdfium.PdfDocument:
    limits = limits or Limits()
    if not is_pdf(data):
        raise ToolError(f"{name}: not a PDF")
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise ToolError(f"{name}: unreadable PDF: {exc}") from exc
    if len(doc) > limits.max_pages:
        doc.close()
        raise ToolError(f"{name}: {len(doc)} pages exceeds --max-pages ({limits.max_pages})")
    return doc


def parse_page_ranges(spec: str | None, page_count: int) -> list[int]:
    """Turn ``"1-3,7,10-"`` into zero-based page indices. ``None`` means all pages."""
    if not spec:
        return list(range(page_count))
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo = int(lo_s) if lo_s else 1
                hi = int(hi_s) if hi_s else page_count
            else:
                lo = hi = int(part)
        except ValueError as exc:
            raise ToolError(f"invalid page range: {part!r}") from exc
        if lo < 1 or hi < lo:
            raise ToolError(f"invalid page range: {part!r}")
        pages.extend(p - 1 for p in range(lo, min(hi, page_count) + 1))
    return sorted(set(pages))
