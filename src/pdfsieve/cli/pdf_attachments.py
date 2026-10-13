"""pdf-attachments: list or extract the files embedded in PDFs."""

from __future__ import annotations

import argparse
import os
import sys

from ..core.attachments import DEFAULT_MAX_ATTACHMENT_BYTES, find_attachments, safe_filename
from ..core.output import EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, add_output_args, run, warn
from ..core.pdfio import add_limit_args, display_name, limits_from_args, open_pikepdf, read_input

PROG = "pdf-attachments"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="List the files embedded in PDFs, or extract them. "
                    "Exit status: 0 if any attachment was found, 1 if none, 2 on error.",
    )
    p.add_argument("files", nargs="+", metavar="PDF", help="input PDF, or - for stdin")
    action = p.add_mutually_exclusive_group()
    action.add_argument("-x", "--extract", metavar="DIR",
                        help="extract every attachment into DIR (one subdirectory per input if several)")
    action.add_argument("-n", "--name", metavar="NAME",
                        help="extract only the attachment called NAME; write it to -o")
    p.add_argument("-o", "--output", metavar="FILE", default="-",
                   help="with --name: output file, or - for stdout (default)")
    p.add_argument("--force", action="store_true", help="overwrite existing files when extracting")
    p.add_argument("--max-attachment-bytes", type=int, default=DEFAULT_MAX_ATTACHMENT_BYTES, metavar="N")
    add_output_args(p)
    add_limit_args(p)
    return p


def _text(rec: dict) -> str:
    rel = f" [{rec['afrelationship']}]" if rec.get("afrelationship") else ""
    where = f" -> {rec['written_to']}" if rec.get("written_to") else ""
    return f"{rec['file']}: {rec['name']}  {rec.get('size')} bytes  {rec.get('mime_type') or '-'}{rel}{where}"


def _unique_path(directory: str, name: str, force: bool, taken: set[str]) -> str:
    base, ext = os.path.splitext(name)
    candidate, n = name, 1
    while candidate in taken or (not force and os.path.exists(os.path.join(directory, candidate))):
        n += 1
        candidate = f"{base}-{n}{ext}"
    taken.add(candidate)
    return os.path.join(directory, candidate)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    limits = limits_from_args(args)
    out = Output(args.output_mode)
    if args.name and args.output == "-":
        out.mode = "quiet"  # stdout carries the file content
    if args.files.count("-") > 1:
        raise ToolError("stdin (-) can only be given once")

    found_any, had_error = False, False
    for path in args.files:
        name = display_name(path)
        try:
            pdf = open_pikepdf(read_input(path, limits), name)
        except ToolError as exc:
            warn(PROG, str(exc))
            had_error = True
            continue
        with pdf:
            attachments = find_attachments(pdf)
            if args.name:
                attachments = [a for a in attachments if a.name == args.name]
            target_dir = None
            if args.extract:
                target_dir = args.extract
                if len(args.files) > 1:
                    target_dir = os.path.join(args.extract, safe_filename(os.path.basename(name)))
                os.makedirs(target_dir, exist_ok=True)
            taken: set[str] = set()
            for att in attachments:
                try:
                    data = att.read(args.max_attachment_bytes)
                except ValueError as exc:
                    warn(PROG, f"{name}: {exc}")
                    had_error = True
                    continue
                found_any = True
                record = {"file": name, **att.to_record(data)}
                if target_dir is not None:
                    dest = _unique_path(target_dir, safe_filename(att.name), args.force, taken)
                    with open(dest, "wb") as fh:
                        fh.write(data)
                    record["written_to"] = dest
                elif args.name:
                    if args.output == "-":
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                    else:
                        if os.path.exists(args.output) and not args.force:
                            raise ToolError(f"{args.output} exists (use --force)")
                        with open(args.output, "wb") as fh:
                            fh.write(data)
                        record["written_to"] = args.output
                    out.emit(record, _text)
                    break  # first match only; names are not unique in every PDF
                out.emit(record, _text)

    if found_any:
        return EXIT_OK
    return EXIT_ERROR if had_error else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
