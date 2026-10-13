"""xrechnung2zugferd: embed an XRechnung / Factur-X CII XML into a PDF (or an image of the invoice),
producing a ZUGFeRD PDF."""

from __future__ import annotations

import argparse
import os
import sys

from ..core.imageio import DEFAULT_DPI, images_to_pdf, open_frames
from ..core.output import EXIT_OK, ToolError, run, warn
from ..core.pdfio import add_limit_args, is_pdf, limits_from_args, read_input
from ..einvoice.embed import RELATIONSHIPS, embed

PROG = "xrechnung2zugferd"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Embed a CII invoice XML (XRechnung, or any ZUGFeRD 2.x / Factur-X profile) into a PDF and "
                    "write a PDF/A-3 with ZUGFeRD/Factur-X metadata. The visual invoice can also be an image "
                    "(scan or photo; one page per frame of a multi-page TIFF). Exit status: 0 if written, 2 on "
                    "error.",
    )
    p.add_argument("pdf", metavar="PDF|IMAGE", help="the visual invoice (PDF or image), or - for stdin")
    p.add_argument("xml", metavar="XML", help="the CII invoice XML, or - for stdin")
    p.add_argument("-o", "--output", metavar="FILE", required=True, help="output PDF, or - for stdout")
    p.add_argument("--relationship", choices=RELATIONSHIPS, default="Alternative",
                   help="AFRelationship of the embedded XML (default: %(default)s)")
    p.add_argument("--attachment-name", default="factur-x.xml",
                   help="name of the embedded file (default: %(default)s, used by ZUGFeRD 2.2+ for every "
                        "profile; ZUGFeRD 2.1.1 used xrechnung.xml for the XRECHNUNG profile)")
    p.add_argument("--image-dpi", type=float, default=DEFAULT_DPI, metavar="DPI",
                   help="page size for images without resolution metadata (default: %(default)s)")
    p.add_argument("--pdfa-convert", action="store_true",
                   help="rewrite the PDF with Ghostscript first (embeds all fonts, RGB colours)")
    p.add_argument("--require-pdfa", action="store_true", help="fail if the input PDF is not already PDF/A")
    p.add_argument("--replace", action="store_true", help="replace an invoice XML the PDF already contains")
    p.add_argument("--no-check", dest="check_xsd", action="store_false",
                   help="skip the XML schema check of the invoice XML")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p.add_argument("-q", "--quiet", action="store_true", help="do not print warnings")
    add_limit_args(p)
    return p


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.pdf == "-" and args.xml == "-":
        raise ToolError("only one of PDF and XML can come from stdin")
    if args.output != "-":
        if args.pdf != "-" and _same_file(args.pdf, args.output):
            raise ToolError("refusing to overwrite the input PDF; choose another -o")
        if os.path.exists(args.output) and not args.force:
            raise ToolError(f"{args.output} exists (use --force)")
    limits = limits_from_args(args)
    pdf = read_input(args.pdf, limits)
    xml = read_input(args.xml, limits)
    image_only = not is_pdf(pdf)
    if image_only:
        pdf = images_to_pdf(open_frames(pdf, args.pdf), default_dpi=args.image_dpi)

    result = embed(pdf, xml, relationship=args.relationship, attachment_name=args.attachment_name,
                   check_xsd=args.check_xsd, replace=args.replace,
                   convert=args.pdfa_convert and not image_only, image_only=image_only)
    not_pdfa = any(w.startswith("input is not PDF/A") for w in result.warnings)
    if args.require_pdfa and not_pdfa:
        raise ToolError("the input PDF is not PDF/A (--require-pdfa)")
    if not args.quiet:
        for w in result.warnings:
            warn(PROG, f"warning: {w}")

    if args.output == "-":
        sys.stdout.buffer.write(result.pdf)
        sys.stdout.buffer.flush()
    else:
        with open(args.output, "wb") as fh:
            fh.write(result.pdf)
    return EXIT_OK


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
