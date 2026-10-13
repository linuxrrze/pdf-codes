"""zugferd2xrechnung: extract the invoice XML from a ZUGFeRD / Factur-X PDF."""

from __future__ import annotations

import argparse
import os
import sys

from ..core.output import EXIT_NOT_FOUND, EXIT_OK, ToolError, run, warn
from ..core.pdfio import add_limit_args, display_name, limits_from_args, open_pikepdf, read_input
from ..einvoice.convert import cii_to_ubl
from ..einvoice.detect import detect

PROG = "zugferd2xrechnung"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Extract the embedded invoice XML from a ZUGFeRD / Factur-X PDF. "
                    "Exit status: 0 if XML was written, 1 if the PDF holds no (acceptable) invoice XML, 2 on error.",
    )
    p.add_argument("file", metavar="PDF", help="input PDF, or - for stdin")
    p.add_argument("-o", "--output", metavar="FILE", default="-", help="output file, or - for stdout (default)")
    p.add_argument("--syntax", choices=("cii", "ubl"), default="cii",
                   help="cii: the embedded XML as is (default); ubl: convert to UBL 2.1 (needs Java, "
                        "see pdfsieve-setup-java)")
    p.add_argument("--strict", action="store_true",
                   help="refuse profiles that are not complete EN 16931 invoices (MINIMUM, BASIC WL, ZUGFeRD 1.0)")
    p.add_argument("--require-xrechnung", action="store_true", help="refuse anything but the XRECHNUNG profile")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    p.add_argument("-q", "--quiet", action="store_true", help="do not print warnings")
    add_limit_args(p)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    name = display_name(args.file)
    if args.output != "-" and os.path.exists(args.output) and not args.force:
        raise ToolError(f"{args.output} exists (use --force)")

    with open_pikepdf(read_input(args.file, limits_from_args(args)), name) as pdf:
        found = detect(pdf)

    def note(message: str) -> None:
        if not args.quiet:
            warn(PROG, f"{name}: {message}")

    if not found.is_einvoice:
        note("no invoice XML embedded")
        return EXIT_NOT_FOUND
    info = found.info
    for w in found.warnings:
        note(f"warning: {w}")
    if args.require_xrechnung and info.profile != "XRECHNUNG":
        note(f"profile is {info.profile}, not XRECHNUNG")
        return EXIT_NOT_FOUND
    if args.strict and not info.en16931_compliant:
        note(f"profile {info.profile} ({info.syntax}) is not a complete EN 16931 invoice")
        return EXIT_NOT_FOUND
    if not info.en16931_compliant:
        note(f"profile {info.profile} is not a complete EN 16931 invoice, so this is not a valid XRechnung")

    xml = found.xml
    if args.syntax == "ubl":
        if info.syntax == "UBL":
            pass  # already UBL
        elif info.syntax == "CII":
            xml = cii_to_ubl(xml)
        else:
            raise ToolError(f"{name}: cannot convert {info.syntax} to UBL (only ZUGFeRD 2.x / Factur-X CII)")
    elif info.syntax == "UBL":
        raise ToolError(f"{name}: the embedded XML is UBL; use --syntax ubl to extract it")

    if args.output == "-":
        sys.stdout.buffer.write(xml)
        sys.stdout.buffer.flush()
    else:
        with open(args.output, "wb") as fh:
            fh.write(xml)
    return EXIT_OK


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
