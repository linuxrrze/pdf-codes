from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from pdfsieve.core.output import ToolError

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CORPUS = FIXTURES / "corpus"
TESTSUITE = FIXTURES / "xrechnung-testsuite" / "instances"


def pytest_collection_modifyitems(config, items):
    have_corpus = CORPUS.exists() and TESTSUITE.exists()
    have_java = _java_ready()
    for item in items:
        if "corpus" in item.keywords and not have_corpus:
            item.add_marker(pytest.mark.skip(reason="run: uv run python tests/fetch_fixtures.py"))
        if "java" in item.keywords and not have_java:
            item.add_marker(pytest.mark.skip(reason="needs Java 17+ and pdfsieve-setup-java"))


def _java_ready() -> bool:
    from pdfsieve.einvoice.java import COMPONENTS, component_path, find_java

    try:
        find_java()
        for key in COMPONENTS:
            component_path(key)
    except ToolError:
        return False
    return True


class Result:
    def __init__(self, code: int, stdout: bytes, stderr: str):
        self.code, self.stdout, self.stderr = code, stdout, stderr

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8")

    @property
    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.text.splitlines() if line.strip()]


@pytest.fixture
def invoke(monkeypatch, capsys):
    """Run a CLI ``main`` like the console script would: ToolError → exit code, stdout captured as bytes."""

    def _invoke(main, *args, stdin: bytes = b"") -> Result:
        out = io.BytesIO()
        fake_stdout = io.TextIOWrapper(out, encoding="utf-8", write_through=True)
        monkeypatch.setattr(sys, "stdout", fake_stdout)
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8"))
        try:
            code = main([str(a) for a in args])
        except ToolError as exc:
            print(str(exc), file=sys.stderr)
            code = exc.code
        except SystemExit as exc:  # argparse errors
            code = exc.code
        fake_stdout.flush()
        return Result(code, out.getvalue(), capsys.readouterr().err)

    return _invoke
