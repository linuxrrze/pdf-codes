"""pdf-codes: find and decode QR codes and barcodes anywhere in PDFs."""

from __future__ import annotations

import argparse
import base64
import os
import sys

from ..codes.classify import classify
from ..codes.scan import ScanOptions, parse_formats, scan_page
from ..core.attachments import safe_filename
from ..core.output import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, add_output_args, run, warn
from ..core.pdfio import add_limit_args, display_name, limits_from_args, open_pdfium, parse_page_ranges, read_input

PROG = "pdf-codes"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Find and decode every QR code and barcode in PDFs, wherever it sits on the page, and "
                    "classify its content (EPC/GiroCode, Swiss QR-bill, GS1, vCard, WiFi, URL, ...). "
                    "Exit status: 0 if any code was found, 1 if none, 2 on error.",
    )
    p.add_argument("files", nargs="+", metavar="PDF", help="input PDF, or - for stdin")
    p.add_argument("--pages", metavar="RANGES", help="pages to scan, e.g. 1-3,7 (default: all)")
    p.add_argument("--symbology", metavar="LIST",
                   help="only these code types, e.g. qr,datamatrix,code128 (default: all)")
    p.add_argument("--dpi", type=float, default=300, help="full-page render resolution (default: %(default)s)")
    p.add_argument("--tile-dpi", type=float, default=600,
                   help="resolution of the tiled pass for small codes (default: %(default)s)")
    p.add_argument("--max-code-mm", type=float, default=60,
                   help="largest code size the tiles must hold whole; sets the tile overlap (default: %(default)s)")
    speed = p.add_mutually_exclusive_group()
    speed.add_argument("--fast", action="store_true", help="full-page pass only (misses very small codes)")
    speed.add_argument("--thorough", action="store_true",
                       help="add a 1200 dpi tile pass and alternative binarisers for faded scans")
    p.add_argument("--no-parse", dest="parse", action="store_false", help="do not classify payloads")
    p.add_argument("--save", metavar="DIR", help="also write each payload to DIR/<file>-p<page>-<n>.txt|.bin")
    p.add_argument("--raw", action="store_true",
                   help="print only the decoded payloads, exactly as decoded, one per line (see -0)")
    p.add_argument("-0", "--null", action="store_true",
                   help="with --raw: end each payload with NUL instead of newline (safe for multi-line "
                        "payloads such as EPC or vCard; a payload that itself contains NUL is reported on "
                        "stderr - use --save or the JSON bytes_b64 for those)")
    add_output_args(p)
    add_limit_args(p)
    return p


def _text(rec: dict) -> str:
    payload = rec.get("payload") or {}
    kind = payload.get("type", "")
    if payload and not payload.get("valid", True):
        kind += "(invalid)"
    shown = rec["text"].replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    flag = " [outside cropbox]" if rec["outside_cropbox"] else ""
    return f"{rec['file']}:{rec['page']}: {rec['symbology']} {kind}{flag}  {shown}"


def _save(directory: str, file_name: str, page: int, n: int, data: bytes) -> str:
    stem = safe_filename(os.path.splitext(os.path.basename(file_name))[0]) or "stdin"
    try:
        data.decode("utf-8")
        ext = "txt"
    except UnicodeDecodeError:
        ext = "bin"
    path = os.path.join(directory, f"{stem}-p{page}-{n}.{ext}")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.null and not args.raw:
        parser.error("-0/--null only applies with --raw")
    if args.files.count("-") > 1:
        raise ToolError("stdin (-) can only be given once")
    try:
        formats = parse_formats(args.symbology)
    except ValueError as exc:
        parser.error(str(exc))
    opts = ScanOptions(dpi=args.dpi, tile_dpi=args.tile_dpi, max_code_mm=args.max_code_mm,
                       tiles=not args.fast, images=not args.fast, thorough=args.thorough, formats=formats)
    limits = limits_from_args(args)
    out = Output("quiet" if args.raw else args.output_mode)
    raw_out = sys.stdout.buffer
    if args.save:
        os.makedirs(args.save, exist_ok=True)

    found_any, had_error = False, False
    for path in args.files:
        name = display_name(path)
        try:
            doc = open_pdfium(read_input(path, limits), name, limits)
        except ToolError as exc:
            warn(PROG, str(exc))
            had_error = True
            continue
        try:
            pages = parse_page_ranges(args.pages, len(doc))
            for index in pages:
                for n, hit in enumerate(scan_page(doc, index, opts), start=1):
                    found_any = True
                    if args.raw and args.output_mode != "quiet":
                        sep = b"\0" if args.null else b"\n"
                        if sep in hit.data:
                            what = "NUL" if args.null else "newline (use -0)"
                            warn(PROG, f"{name}: page {hit.page}: payload contains a {what}; the output "
                                       "cannot be split unambiguously")
                        raw_out.write(hit.data + sep)
                        raw_out.flush()
                    record = {
                        "file": name,
                        "page": hit.page,
                        "symbology": hit.symbology,
                        "symbology_identifier": hit.aim,
                        "content_type": hit.content_type,
                        "bbox_pt": [round(v, 2) for v in hit.bbox],
                        "outside_cropbox": hit.outside_cropbox,
                        "source": hit.sources,
                        "text": hit.text,
                        "bytes_b64": base64.b64encode(hit.data).decode("ascii"),
                    }
                    if args.parse:
                        record["payload"] = classify(hit.data, hit.aim)
                    if args.save:
                        record["saved_to"] = _save(args.save, name, hit.page, n, hit.data)
                    out.emit(record, _text)
        finally:
            doc.close()

    if found_any:
        return EXIT_OK
    return EXIT_ERROR if had_error else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
