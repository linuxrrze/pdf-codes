"""code-reparse: refresh the payloads in code-scan JSON Lines with the current parsers, without re-scanning."""

from __future__ import annotations

import argparse
import base64
import binascii
import collections
import json
import os
import sys
import tempfile
import time

from ..codes.classify import classify
from ..core.output import (EXIT_NOT_FOUND, EXIT_OK, Output, ToolError, _json_default, add_output_args, run,
                           warn)

PROG = "code-reparse"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Re-classify the payloads in code-scan JSON Lines output with the current parsers. Each "
                    "record's payload is rebuilt from its bytes_b64 and symbology_identifier; every other "
                    "field is kept. Much faster than scanning the documents again after a parser was added "
                    "or improved. Exit status: 0 if any payload changed, 1 if none did, 2 on error.",
    )
    p.add_argument("files", nargs="*", metavar="FILE", help="code-scan JSON Lines files (default: stdin)")
    p.add_argument("-i", "--in-place", action="store_true",
                   help="rewrite each changed file instead of printing records; unchanged files are left alone")
    p.add_argument("--min-age", type=float, default=60, metavar="SECONDS",
                   help="with --in-place: skip files modified less than SECONDS ago, as a scan may still be "
                        "writing them (default: 60)")
    p.add_argument("--changed", action="store_true", help="print only records whose payload changed")
    p.add_argument("--summary", action="store_true",
                   help="print on stderr how many payloads changed, by old and new type")
    add_output_args(p)
    return p


def _payload_bytes(rec: dict) -> bytes | None:
    if "bytes_b64" in rec:
        try:
            return base64.b64decode(rec["bytes_b64"], validate=True)
        except (binascii.Error, TypeError):
            return None
    if isinstance(rec.get("text"), str):
        return rec["text"].encode("utf-8")
    return None


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, default=_json_default)


def reparse_line(line: str, where: str) -> tuple[dict | None, bool, str | None]:
    """Return (record or None if the line is not a code record, whether the payload changed, old type)."""
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        warn(PROG, f"{where}: not JSON, kept as is")
        return None, False, None
    if not isinstance(rec, dict) or "symbology" not in rec:
        warn(PROG, f"{where}: not a code-scan record, kept as is")
        return None, False, None
    data = _payload_bytes(rec)
    if data is None:
        warn(PROG, f"{where}: no usable bytes_b64 or text, kept as is")
        return None, False, None
    old = rec.get("payload")
    new = classify(data, rec.get("symbology_identifier"))
    changed = _canonical(old) != _canonical(new)
    rec["payload"] = new  # keeps the key's position when it was there already
    return rec, changed, (old or {}).get("type")


def _text(rec: dict) -> str:
    return f"{rec.get('file', '?')}:{rec.get('page', '?')}: {rec['payload']['type']}"


def _write_in_place(path: str, lines: list[str], before: os.stat_result) -> bool:
    """Atomically replace ``path``; refuse if it changed since it was read."""
    now = os.stat(path)
    if (now.st_size, now.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        warn(PROG, f"{path}: changed while being read, left alone")
        return False
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".code-reparse-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(tmp, before.st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sources = args.files or ["-"]
    if args.in_place and "-" in sources:
        raise ToolError("--in-place needs file names, not stdin")
    out = Output(args.output_mode)
    transitions: collections.Counter = collections.Counter()
    records = changed_records = 0

    for source in sources:
        try:
            if source == "-":
                text, before = sys.stdin.read(), None
            else:
                before = os.stat(source)
                if args.in_place and time.time() - before.st_mtime < args.min_age:
                    warn(PROG, f"{source}: modified less than {args.min_age:g} s ago, skipped")
                    continue
                with open(source, encoding="utf-8") as fh:
                    text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"{source}: {getattr(exc, 'strerror', None) or exc}") from exc

        new_lines, file_changed = [], False
        for number, line in enumerate(text.splitlines(keepends=True), start=1):
            if not line.strip():
                new_lines.append(line)
                continue
            rec, changed, old_type = reparse_line(line, f"{source}:{number}")
            if rec is None:
                new_lines.append(line)
                continue
            records += 1
            if changed:
                changed_records += 1
                file_changed = True
                transitions[(old_type, rec["payload"]["type"])] += 1
            if args.in_place:
                ending = "\n" if line.endswith("\n") else ""
                new_lines.append(json.dumps(rec, ensure_ascii=False, default=_json_default) + ending)
            elif changed or not args.changed:
                out.emit(rec, _text)
        if args.in_place and file_changed:
            _write_in_place(source, new_lines, before)

    if args.summary:
        warn(PROG, f"{records} records, {changed_records} payloads changed")
        for (old, new), n in transitions.most_common():
            warn(PROG, f"  {n:6}  {old or '(none)'} -> {new}")
    return EXIT_OK if changed_records else EXIT_NOT_FOUND


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
