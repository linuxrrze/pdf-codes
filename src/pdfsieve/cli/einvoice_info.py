"""einvoice-info: detect ZUGFeRD / Factur-X / XRechnung in PDFs."""

from __future__ import annotations

import argparse

from ..core.output import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, add_output_args, run, warn
from ..core.pdfio import add_limit_args, display_name, limits_from_args, open_pikepdf, read_input
from ..einvoice.detect import detect

PROG = "einvoice-info"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Report whether PDFs are ZUGFeRD / Factur-X / XRechnung e-invoices, with standard, "
                    "profile and consistency warnings. Exit status: 0 if any input is an e-invoice, "
                    "1 if none is, 2 on error.",
    )
    p.add_argument("files", nargs="+", metavar="PDF", help="input PDF, or - for stdin")
    p.add_argument("--strict", action="store_true",
                   help="count only EN 16931-compliant profiles (BASIC and up) as e-invoices")
    p.add_argument("--require-xrechnung", action="store_true",
                   help="count only the XRECHNUNG profile as an e-invoice")
    p.add_argument("--warnings-fail", action="store_true",
                   help="treat files with consistency warnings as not matching")
    add_output_args(p)
    add_limit_args(p)
    return p


def _text(rec: dict) -> str:
    if not rec["einvoice"]:
        return f"{rec['file']}: no e-invoice"
    xr = f" {rec['xrechnung_version']}" if rec.get("xrechnung_version") else ""
    head = (f"{rec['file']}: {rec['standard']}, profile {rec['profile']}{xr}, {rec['syntax']}, "
            f"{rec['xml']['name']}")
    return "\n".join([head] + [f"  warning: {w}" for w in rec["warnings"]])


def matches(rec: dict, args: argparse.Namespace) -> bool:
    if not rec["einvoice"]:
        return False
    if args.require_xrechnung and rec["profile"] != "XRECHNUNG":
        return False
    if args.strict and not rec["en16931_compliant"]:
        return False
    return not (args.warnings_fail and rec["warnings"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limits = limits_from_args(args)
    out = Output(args.output_mode)
    if args.files.count("-") > 1:
        raise ToolError("stdin (-) can only be given once")

    any_match, had_error = False, False
    for path in args.files:
        name = display_name(path)
        try:
            pdf = open_pikepdf(read_input(path, limits), name)
        except ToolError as exc:
            warn(PROG, str(exc))
            had_error = True
            continue
        with pdf:
            rec = {"file": name, **detect(pdf).record}
        rec["match"] = matches(rec, args)
        any_match = any_match or rec["match"]
        out.emit(rec, _text)

    if any_match:
        return EXIT_OK
    return EXIT_ERROR if had_error else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
