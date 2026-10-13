"""KBV Blankoformular barcodes. All patient data here is invented."""

from __future__ import annotations

import pytest

from code_tools.codes.classify import classify
from code_tools.codes.parsers import kbv


def muster6(**overrides) -> bytes:
    values = dict.fromkeys(kbv.FIELD_TABLES[("06", "12")], "")
    values.update({
        "Formularcode": "06", "Versionsnummer": "12", "Nachname": "Mustermann", "Vorname": "Erika",
        "Geburtsdatum": "19640812", "Kostenträgername": "Musterkasse", "(N)BSNR Überweiser": "123456700",
        "Überweiser LANR": "999999900", "Ausstellungsdatum": "20260101", "Geschlecht": "W", "PLZ": "12345",
        "Ort": "Musterstadt", "Straße": "Musterweg", "Hausnummer": "1", "Wohnsitzländercode": "D",
        "Kurativ/Präventiv/bei belegärztl. Behandlung": "1", "Überweisung an": "Orthopädie",
        "Untersuchungsart": "2", "Diagnose/Verdachtsdiagnose": "Gonarthrose (M17.1 G R), Z.n. Sturz (S80.0 Z L)",
        "Auftrag": "Bitte um Mitbeurteilung",
    })
    values.update(overrides)
    return "\t".join(values.values()).encode("iso-8859-15")


def test_muster6_fields():
    p = classify(muster6(), "]L2")
    assert p["type"] == "kbv_form" and p["valid"], p["errors"]
    assert (p["form"], p["name"], p["version"], p["copy"]) == ("6", "Überweisungsschein", "12", None)
    assert p["fields"]["Nachname"] == "Mustermann"
    assert p["fields"]["Überweisung an"] == "Orthopädie"  # ISO 8859-15 umlaut
    assert "Titel" not in p["fields"]  # empty fields are left out
    assert p["decoded"] == {
        "Geburtsdatum": "1964-08-12", "Ausstellungsdatum": "2026-01-01", "Geschlecht": "weiblich",
        "Kurativ/Präventiv/bei belegärztl. Behandlung": "kurativ", "Untersuchungsart": "Konsiliaruntersuchung"}
    assert p["icd10"] == [{"code": "M17.1", "certainty": "G", "side": "R"},
                          {"code": "S80.0", "certainty": "Z", "side": "L"}]
    assert p["warnings"] == []


def test_muster6_problems_are_reported():
    p = classify(muster6(Geschlecht="Q", Geburtsdatum="1964-08-12"), "]L2")
    assert p["valid"]  # structure intact, values odd
    assert any("Geschlecht" in w for w in p["warnings"])
    assert any("Geburtsdatum" in w for w in p["warnings"])
    short = classify(muster6()[: muster6().rindex(b"\t")], "]L2")
    assert not short["valid"] and "40 fields" in short["errors"][0]


def test_other_forms_and_versions_are_recognised_without_names():
    p = classify(b"10\tA\t08\t\tMustermann\tErika", "]L2")
    assert p["type"] == "kbv_form" and p["form"] == "10A"
    assert p["name"] == "Anforderungsschein für Laboratoriumsuntersuchungen bei Laborgemeinschaften"
    assert p["fields_raw"][4] == "Mustermann" and "no field table" in p["warnings"][0]
    assert classify(b"61\tAb\t07\tx\ty", "]L2")["form"] == "61A"
    assert classify(b"61\tAb\t07\tx\ty", "]L2")["copy"] == "b"
    assert classify(b"06\t\t11\tx\ty", "]L2")["warnings"]  # older Muster 6 version: no table here


@pytest.mark.parametrize("payload, aim", [
    (b"06\t\t12\tx\ty", "]Q1"),            # not PDF417
    (b"99\t\t12\tx\ty", "]L2"),            # no such form
    (b"06\t\tAB\tx\ty", "]L2"),            # version not numeric
    (b"06 12 Mustermann", "]L2"),          # no tabs
    (b"06\t\t12", "]L2"),                  # too few fields
])
def test_not_kbv(payload, aim):
    assert classify(payload, aim)["type"] != "kbv_form"


def test_icd_parsing():
    assert kbv.parse_icd10("O26.83 G, O12.2 Z, S51.9 G L") == [
        {"code": "O26.83", "certainty": "G", "side": None},
        {"code": "O12.2", "certainty": "Z", "side": None},
        {"code": "S51.9", "certainty": "G", "side": "L"}]
    assert kbv.parse_icd10("Kontrolle") == []
