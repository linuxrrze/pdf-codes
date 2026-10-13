"""CII → UBL conversion via phax en16931-cii2ubl (Java)."""

from __future__ import annotations

import pathlib
import tempfile

from ..core.output import ToolError
from .java import component_path, run_jar


def cii_to_ubl(cii: bytes) -> bytes:
    jar = component_path("cii2ubl")
    with tempfile.TemporaryDirectory(prefix="code-tools-cii2ubl-") as tmp:
        src = pathlib.Path(tmp) / "invoice.xml"
        out_dir = pathlib.Path(tmp) / "out"
        out_dir.mkdir()
        src.write_bytes(cii)
        proc = run_jar(jar, ["-t", str(out_dir), str(src)])
        result = out_dir / "invoice-ubl.xml"
        # The converter exits 0 even when it fails, so the output file is the success signal.
        if not result.exists():
            errors = [line.removeprefix("[ERROR]").strip()
                      for line in (proc.stdout + proc.stderr).splitlines() if line.startswith("[ERROR]")]
            detail = "; ".join(dict.fromkeys(e for e in errors if e)) or f"exit status {proc.returncode}"
            raise ToolError(f"CII to UBL conversion failed: {detail.replace(str(src), 'invoice.xml')}")
        return result.read_bytes()
