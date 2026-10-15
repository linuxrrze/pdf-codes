"""E-Rezept token DataMatrix. Prescription IDs and access codes are invented, with computed check digits."""

from __future__ import annotations

import json

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers.erezept import prescription_id_valid


def rx_id(flow: str, number: int) -> str:
    digits = f"{flow}{number:012d}"
    check = 98 - int(digits) * 100 % 97
    d = f"{digits}{check:02d}"
    return ".".join([d[0:3], d[3:6], d[6:9], d[9:12], d[12:15], d[15:]])


AC = "0123456789abcdef" * 4


def token(*urls) -> bytes:
    return json.dumps({"urls": list(urls)}).encode()


def test_single_prescription():
    rid = rx_id("160", 123456789)
    p = classify(token(f"Task/{rid}/$accept?ac={AC}"), "]d1")
    assert p["type"] == "erezept" and p["valid"] and p["warnings"] == [], p["errors"]
    assert p["prescriptions"] == [{"prescription_id": rid, "flow_type": "160",
                                   "flow_type_name": "Muster 16 (statutory insurance, pharmacy-only medicines)",
                                   "access_code": AC}]
    assert "redeems" in p["note"]


def test_collective_code_and_pkv():
    urls = [f"Task/{rx_id(flow, n)}/$accept?ac={AC}" for flow, n in (("200", 1), ("209", 2), ("169", 3))]
    p = classify(token(*urls))
    assert p["valid"] and [rx["flow_type"] for rx in p["prescriptions"]] == ["200", "209", "169"]


def test_check_digits_match_gematik_example():
    assert prescription_id_valid("160.000.033.491.280.78")  # example from the gematik specification
    assert not prescription_id_valid("160.000.033.491.280.79")


def test_problems():
    rid = rx_id("160", 5)
    bad = rid[:-2] + f"{(int(rid[-2:]) + 1) % 100:02d}"
    p = classify(token(f"Task/{bad}/$accept?ac={AC}"), "]d1")
    assert not p["valid"] and "check digits" in p["errors"][0]
    p = classify(token(f"Task/{rid}/$accept?ac=abc"), "]d1")
    assert not p["valid"] and "64 hex digits" in p["errors"][0]
    p = classify(token(f"Task/{rid}/accept"), "]d1")
    assert p["type"] == "erezept" and not p["valid"]
    p = classify(token(f"Task/{rx_id('999', 5)}/$accept?ac={AC}"), "]d1")
    assert p["valid"] and "unknown flow type 999" in p["warnings"][0]
    p = classify(token(*[f"Task/{rid}/$accept?ac={AC}"] * 4), "]d1")
    assert p["valid"] and "at most 3" in p["warnings"][0]


@pytest.mark.parametrize("payload, aim", [
    (token(f"Task/{rx_id('160', 1)}/$accept?ac={AC}"), "]Q1"),  # E-Rezept tokens are DataMatrix
    (b'{"urls": "Task/1"}', "]d1"),
    (b'{"links": ["Task/160.000.000.000.000.57"]}', "]d1"),
    (b'{"urls": ["https://example.org/Task/1"]}', "]d1"),
    (b"Task/160.000.000.000.000.57/$accept?ac=" + AC.encode(), "]d1"),  # not JSON
])
def test_not_erezept(payload, aim):
    assert classify(payload, aim)["type"] != "erezept"
