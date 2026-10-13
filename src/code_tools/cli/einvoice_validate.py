"""einvoice-validate: validate an e-invoice (XML, or the XML inside a PDF) with the KoSIT validator."""

from __future__ import annotations

import argparse

from ..core.output import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, add_output_args, run, warn
from ..core.pdfio import add_limit_args, display_name, is_pdf, limits_from_args, open_pikepdf, read_input
from ..einvoice.detect import detect
from ..einvoice.validate import validate_xml

PROG = "einvoice-validate"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Validate XRechnung / EN 16931 invoices with the KoSIT validator (XML Schema, EN 16931 and "
                    "XRechnung Schematron). Inputs may be XML files or ZUGFeRD PDFs. Needs Java and "
                    "code-tools-setup-java. Exit status: 0 if all inputs are valid, 1 if any is invalid, 2 on error.",
    )
    p.add_argument("files", nargs="+", metavar="FILE", help="invoice XML or PDF, or - for stdin")
    p.add_argument("--report-dir", metavar="DIR", help="also keep the full KoSIT XML report in DIR/<n>/")
    p.add_argument("--warnings-fail", action="store_true", help="treat validator warnings as failures")
    add_output_args(p)
    add_limit_args(p)
    return p


def _text(rec: dict) -> str:
    status = "valid" if rec["valid"] else "INVALID"
    lines = [f"{rec['file']}: {status} ({rec.get('scenario') or 'no scenario'})"]
    for level in ("errors", "warnings"):
        for msg in rec[level]:
            lines.append(f"  {level[:-1]}: [{msg.get('code')}] {msg['text']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limits = limits_from_args(args)
    out = Output(args.output_mode)
    if args.files.count("-") > 1:
        raise ToolError("stdin (-) can only be given once")

    all_valid, had_error = True, False
    for n, path in enumerate(args.files, start=1):
        name = display_name(path)
        try:
            data = read_input(path, limits)
            source = "xml"
            if is_pdf(data):
                with open_pikepdf(data, name) as pdf:
                    found = detect(pdf)
                if not found.is_einvoice:
                    raise ToolError(f"{name}: no invoice XML embedded")
                data, source = found.xml, f"pdf:{found.record['xml']['name']}"
            report_dir = f"{args.report_dir}/{n}" if args.report_dir else None
            result = validate_xml(data, keep_report=report_dir)
        except ToolError as exc:
            warn(PROG, str(exc))
            had_error = True
            continue
        if args.warnings_fail and result["warnings"]:
            result["valid"] = False
        all_valid = all_valid and result["valid"]
        out.emit({"file": name, "source": source, **result}, _text)

    if had_error:
        return EXIT_ERROR
    return EXIT_OK if all_valid else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
