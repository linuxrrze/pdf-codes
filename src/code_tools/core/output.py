"""Output conventions shared by every tool.

- Records go to stdout as JSON Lines (default), as text (``--text``), or nowhere (``-q``).
- Diagnostics go to stderr.
- Exit codes work like grep's: 0 found/ok, 1 not found/invalid, 2 usage error or unreadable input.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections.abc import Callable
from typing import Any, NoReturn

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_ERROR = 2


class ToolError(Exception):
    """An expected failure (bad input, missing dependency). Printed without a traceback, exit 2."""

    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


def warn(prog: str, message: str) -> None:
    print(f"{prog}: {message}", file=sys.stderr)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


class Output:
    """Writes records in the mode chosen on the command line."""

    def __init__(self, mode: str = "json", stream=None):
        self.mode = mode  # "json" | "text" | "quiet"
        self.stream = stream or sys.stdout

    def emit(self, record: dict, text: Callable[[dict], str] | None = None) -> None:
        if self.mode == "quiet":
            return
        if self.mode == "text":
            line = text(record) if text else _default_text(record)
            self.stream.write(line + "\n")
        else:
            self.stream.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
        self.stream.flush()


def _default_text(record: dict) -> str:
    return "  ".join(f"{k}={v}" for k, v in record.items() if v not in (None, [], {}))


def add_output_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--text", dest="output_mode", action="store_const", const="text",
                       help="human-readable output instead of JSON Lines")
    group.add_argument("-q", "--quiet", dest="output_mode", action="store_const", const="quiet",
                       help="print nothing, only set the exit code")
    parser.set_defaults(output_mode="json")


def run(main: Callable[[list[str] | None], int], argv: list[str] | None = None) -> NoReturn:
    """Run a CLI main function with uniform error handling and exit codes."""
    prog = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "code-tools"
    try:
        code = main(argv)
    except ToolError as exc:
        warn(prog, str(exc))
        code = exc.code
    except BrokenPipeError:
        # Downstream closed the pipe (e.g. `| head`); not an error for us.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = EXIT_OK
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
