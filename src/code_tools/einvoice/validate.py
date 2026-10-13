"""Validate an invoice XML with the KoSIT validator and the XRechnung configuration."""

from __future__ import annotations

import pathlib
import tempfile

from lxml import etree

from ..core.output import ToolError
from ..core.xmlsafe import parse_xml
from .java import component_path, run_jar

REP_NS = {"rep": "http://www.xoev.de/de/validator/varl/1", "s": "http://www.xoev.de/de/validator/framework/1/scenarios"}


def validate_xml(xml: bytes, keep_report: str | None = None) -> dict:
    """Return ``{"valid", "scenario", "errors", "warnings", "information"}`` from the KoSIT report.

    ``keep_report``: a directory to copy the KoSIT XML report into.
    """
    jar = component_path("kosit")
    config = component_path("xrechnung-config")
    with tempfile.TemporaryDirectory(prefix="code-tools-kosit-") as tmp:
        src = pathlib.Path(tmp) / "invoice.xml"
        src.write_bytes(xml)
        out_dir = pathlib.Path(tmp) / "out"
        out_dir.mkdir()
        proc = run_jar(jar, ["-s", str(config / "scenarios.xml"), "-r", str(config), "-o", str(out_dir), str(src)])
        report_path = out_dir / "invoice-report.xml"
        if not report_path.exists():
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-5:])
            raise ToolError(f"KoSIT validator produced no report (exit {proc.returncode}): {tail}")
        report = report_path.read_bytes()
        if keep_report:
            dest = pathlib.Path(keep_report)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "kosit-report.xml").write_bytes(report)
    return parse_report(report)


def parse_report(report: bytes) -> dict:
    root = parse_xml(report)
    accepted = bool(root.xpath("rep:assessment/rep:accept", namespaces=REP_NS))
    scenario = root.xpath("string(rep:scenarioMatched/s:scenario/s:name)", namespaces=REP_NS) or None
    result: dict = {
        "valid": accepted,
        "schema_valid": root.get("valid") == "true",
        "scenario": scenario,
        "errors": [],
        "warnings": [],
        "information": [],
    }
    if root.xpath("rep:noScenarioMatched", namespaces=REP_NS):
        result["errors"].append({"code": "no-scenario",
                                 "text": "no XRechnung validation scenario matches this document "
                                         "(only XRechnung CII/UBL invoices are covered)"})
    for msg in root.iter(etree.QName(REP_NS["rep"], "message").text):
        entry = {"code": msg.get("code"), "text": " ".join("".join(msg.itertext()).split()),
                 "location": msg.get("xpathLocation")}
        level = msg.get("level", "error")
        key = {"error": "errors", "warning": "warnings"}.get(level, "information")
        result[key].append(entry)
    return result
