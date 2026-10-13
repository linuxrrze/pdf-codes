"""code-parse: classify and parse barcode payloads read from stdin or files."""

from __future__ import annotations

import argparse
import sys

from ..codes.classify import classify
from ..codes.parsers.gs1 import GS1_AIM
from ..core.output import EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, add_output_args, run

PROG = "code-parse"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Classify barcode payloads (EPC/GiroCode, Swiss QR-bill, GS1, vCard, WiFi, URL, ...) and "
                    "parse them into JSON. Reads one payload per line, NUL-separated payloads with -0 "
                    "(matches `pdf-codes --raw -0`), or the whole input as one payload with --whole. "
                    "Exit status: 0 if any payload was recognised, 1 if all were raw, 2 on error.",
    )
    p.add_argument("files", nargs="*", metavar="FILE", help="input files (default: stdin)")
    sep = p.add_mutually_exclusive_group()
    sep.add_argument("-0", "--null", action="store_true", help="payloads are separated by NUL bytes")
    sep.add_argument("--whole", action="store_true", help="each input is a single payload")
    p.add_argument("--aim", metavar="ID",
                   help="AIM symbology identifier to assume, e.g. ]d2 for GS1 DataMatrix (enables GS1 parsing "
                        "of raw element strings)")
    add_output_args(p)
    return p


def _payloads(data: bytes, args: argparse.Namespace) -> list[bytes]:
    if args.whole:
        return [data]
    if args.null:
        parts = data.split(b"\0")
    else:
        parts = [line.rstrip(b"\r") for line in data.split(b"\n")]
    if parts and parts[-1] == b"":
        parts.pop()  # trailing separator
    return parts


def _text(rec: dict) -> str:
    payload = rec["payload"]
    status = "" if payload.get("valid") else " (invalid: " + "; ".join(payload.get("errors", [])) + ")"
    return f"{rec['input']}:{rec['index']}: {payload['type']}{status}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.aim and args.aim not in GS1_AIM and not (len(args.aim) == 3 and args.aim[0] == "]"):
        parser.error(f"--aim must look like ]Q3, not {args.aim!r}")
    out = Output(args.output_mode)
    sources = args.files or ["-"]

    recognised = False
    for source in sources:
        try:
            if source == "-":
                data = sys.stdin.buffer.read()
            else:
                with open(source, "rb") as fh:
                    data = fh.read()
        except OSError as exc:
            raise ToolError(f"{source}: {exc.strerror or exc}") from exc
        for index, payload in enumerate(_payloads(data, args), start=1):
            result = classify(payload, args.aim)
            recognised = recognised or result["type"] != "raw"
            out.emit({"input": "<stdin>" if source == "-" else source, "index": index,
                      "text": payload.decode("utf-8", "replace"), "payload": result}, _text)
    return EXIT_OK if recognised else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
