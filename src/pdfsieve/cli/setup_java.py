"""pdfsieve-setup-java: download the pinned Java components into the cache, verifying checksums."""

from __future__ import annotations

import argparse
import hashlib
import io
import pathlib
import shutil
import tempfile
import urllib.request
import zipfile

from ..core.output import EXIT_OK, ToolError, run
from ..einvoice.java import COMPONENTS, Component, cache_dir, find_java

PROG = "pdfsieve-setup-java"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Download the KoSIT validator, the XRechnung validator configuration and the CII→UBL "
                    f"converter into {cache_dir()} (pinned versions, SHA-256 verified).",
    )
    p.add_argument("components", nargs="*", metavar="COMPONENT",
                   help=f"what to install: {', '.join(COMPONENTS)} (default: all)")
    p.add_argument("--force", action="store_true", help="download again even if present")
    return p


def _download(comp: Component) -> bytes:
    try:
        with urllib.request.urlopen(comp.url, timeout=120) as resp:
            data = resp.read()
    except OSError as exc:
        raise ToolError(f"downloading {comp.url} failed: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != comp.sha256:
        raise ToolError(f"checksum mismatch for {comp.url}: expected {comp.sha256}, got {digest}")
    return data


def _unzip(data: bytes, dest: pathlib.Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(root):
                raise ToolError(f"refusing unsafe archive member {member.filename!r}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))


def install(comp: Component, force: bool = False) -> pathlib.Path:
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    final = cache / comp.target
    if final.exists() and not force:
        print(f"{comp.description}: already installed at {final}")
        return final
    print(f"{comp.description}: downloading {comp.url}")
    data = _download(comp)
    # Write into a temporary sibling, then move into place, so an interrupted run leaves nothing half-done.
    with tempfile.TemporaryDirectory(dir=cache, prefix=".partial-") as tmp:
        staged = pathlib.Path(tmp) / comp.target
        if comp.unzip:
            staged.mkdir()
            _unzip(data, staged)
        else:
            staged.write_bytes(data)
        if final.exists():
            shutil.rmtree(final) if final.is_dir() else final.unlink()
        staged.rename(final)
    print(f"{comp.description}: installed at {final}")
    return final


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    unknown = [c for c in args.components if c not in COMPONENTS]
    if unknown:
        parser.error(f"unknown component(s): {', '.join(unknown)}")
    for key in args.components or list(COMPONENTS):
        install(COMPONENTS[key], args.force)
    try:
        print(f"Java: {find_java()}")
    except ToolError as exc:
        print(f"note: {exc}")
    return EXIT_OK


def cli() -> None:
    run(main)


if __name__ == "__main__":
    cli()
