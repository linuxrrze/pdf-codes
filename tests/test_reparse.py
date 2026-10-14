"""code-reparse: refresh payloads in existing code-scan output. All payloads are invented."""

from __future__ import annotations

import base64
import json
import os
import time

from PIL import Image

from pdfgen import matrix_image, qr_matrix
from code_tools.cli import code_reparse, code_scan
from code_tools.codes.classify import classify

BEIHILFE = "H001;V 04.2019;0f8e9d7c-1a2b-4c3d-8e9f-0123456789ab;1;12345678;Mustermann;Erika;".encode()


def record(data: bytes, aim: str, payload: dict | None, **extra) -> dict:
    """A code-scan record as an older version would have written it."""
    rec = {"file": "letter.pdf", "page": 1, "symbology": "QRCode", "symbology_identifier": aim,
           "text": data.decode("utf-8", "replace"), "bytes_b64": base64.b64encode(data).decode(), **extra}
    if payload is not None:
        rec["payload"] = payload
    return rec


def jsonl(*records) -> str:
    return "".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) + "\n" for r in records)


STALE = record(BEIHILFE, "]Q1", {"type": "raw", "valid": True, "errors": []})
CURRENT = record(b"https://example.org", "]Q1", classify(b"https://example.org", "]Q1"))


def test_stdout_and_changed(invoke):
    r = invoke(code_reparse.main, stdin=jsonl(STALE, CURRENT).encode())
    assert r.code == 0, r.stderr
    assert [rec["payload"]["type"] for rec in r.records] == ["beihilfe_form", "url"]
    assert list(r.records[0]) == list(STALE)  # same fields, same order
    r = invoke(code_reparse.main, "--changed", "--summary", stdin=jsonl(STALE, CURRENT).encode())
    assert [rec["payload"]["type"] for rec in r.records] == ["beihilfe_form"]
    assert "2 records, 1 payloads changed" in r.stderr and "raw -> beihilfe_form" in r.stderr
    assert invoke(code_reparse.main, stdin=jsonl(CURRENT).encode()).code == 1  # nothing changed


def test_records_without_payload_and_odd_lines(invoke):
    no_parse = record(BEIHILFE, "]Q1", None)  # written with code-scan --no-parse
    partial = '{"file": "a.pdf", "sym'  # a scan still running may leave a half-written last line
    r = invoke(code_reparse.main, stdin=jsonl(no_parse, '{"other": 1}\n', partial).encode())
    assert [rec["payload"]["type"] for rec in r.records] == ["beihilfe_form"]
    assert "not a code-scan record" in r.stderr and "not JSON" in r.stderr


def test_in_place(invoke, tmp_path):
    path = tmp_path / "scan.jsonl"
    content = jsonl(STALE, "not json\n", CURRENT)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o640)
    old = time.time() - 3600
    os.utime(path, (old, old))

    r = invoke(code_reparse.main, "-i", path)
    assert r.code == 0 and r.stdout == b""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["payload"]["type"] == "beihilfe_form"
    assert lines[1] == "not json" and json.loads(lines[2]) == CURRENT  # other lines untouched
    assert os.stat(path).st_mode & 0o777 == 0o640
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".code-reparse-")]

    os.utime(path, (old, old))
    mtime = os.stat(path).st_mtime_ns
    assert invoke(code_reparse.main, "-i", path).code == 1  # already current: file not rewritten
    assert os.stat(path).st_mtime_ns == mtime


def test_in_place_skips_files_being_written(invoke, tmp_path):
    path = tmp_path / "scan.jsonl"
    path.write_text(jsonl(STALE), encoding="utf-8")  # just modified, like a running scan's output
    r = invoke(code_reparse.main, "-i", path)
    assert r.code == 1 and "skipped" in r.stderr
    assert path.read_text(encoding="utf-8") == jsonl(STALE)
    assert invoke(code_reparse.main, "-i", "--min-age", "0", path).code == 0
    assert invoke(code_reparse.main, "-i", stdin=b"").code == 2  # stdin cannot be rewritten


def test_matches_a_fresh_scan(invoke, tmp_path):
    image = tmp_path / "scan.png"
    page = Image.new("L", (600, 600), "white")
    page.paste(matrix_image(qr_matrix(BEIHILFE), 4), (50, 50))
    page.save(image)
    scanned = invoke(code_scan.main, "--fast", "--no-parse", image)
    reparsed = invoke(code_reparse.main, stdin=scanned.stdout)
    fresh = invoke(code_scan.main, "--fast", image)
    assert reparsed.records == fresh.records
