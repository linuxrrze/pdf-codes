"""KBV Blankoformularbedruckung: the PDF417 barcode on German statutory medical forms ("Muster").

Specification: KBV, Technisches Handbuch Blankoformularbedruckung (version 4.80, 13 May 2026),
https://update.kbv.de/ita-update/Blankoformulare/KBV_ITA_VGEX_Technisches_Handbuch_BFB.pdf

Layout (chapter 2): fields separated by TAB, every field present even if empty, no TAB after the last
field, ISO 8859-15. Every form starts with
    01 Formularcode (2 digits, the form number), 02 Formularcodeergänzung (variant/copy letters),
    03 Versionsnummer (2 digits, the barcode version of that form).
The field tables per form are in chapter 3; field names are decoded for the tables in ``FIELD_TABLES``.

The barcode is not encrypted and usually contains health data (diagnoses, insurer, date of birth).
"""

from __future__ import annotations

import re

TYPE = "kbv_form"

# Form numbers with a barcode table in the handbook (chapter 3). Muster 1 was dropped in version 4.61 (2021)
# when the electronic AU certificate (eAU) replaced it, but printouts with its barcode still circulate.
FORMS_WITH_BARCODE = {1, 2, 3, 4, 6, 8, 9, 10, 11, 12, 13, 15, 19, 20, 21, 25, 26, 27, 28, 36, 39, 50, 51, 52, 53,
                      55, 56, 61, 62, 63, 64, 65, 70}

# Official form names: the "DN" attribute of the KBV Ausfüllhilfe XML files
# (https://update.kbv.de/ita-update/Blankoformulare/Ausfuellhilfe.zip), plus names the handbook quotes.
# Keyed by form number plus the upper-case variant letters of the Formularcodeergänzung.
FORM_NAMES = {
    "1": "Arbeitsunfähigkeitsbescheinigung",
    "4": "Verordnung einer Krankenbeförderung",
    "6": "Überweisungsschein",
    "8": "Sehhilfenverordnung",
    "8A": "Verordnung von vergrößernden Sehhilfen",
    "9": "Bescheinigung einer Fehlgeburt, Frühgeburt oder Behinderung des Kindes",
    "10": "Überweisungsschein für in-vitro-diagnostische Auftragsleistungen",
    "10A": "Anforderungsschein für Laboratoriumsuntersuchungen bei Laborgemeinschaften",
    "12": "Verordnung häuslicher Krankenpflege",
    "13": "Heilmittelverordnung",
    "20": "Stufenweise Wiedereingliederung in das Erwerbsleben (Wiedereingliederungsplan)",
    "21": "Ärztliche Bescheinigung für den Bezug von Krankengeld bei Erkrankung eines Kindes",
    "26": "Verordnung Soziotherapie",
    "27": "Soziotherapeutischer Betreuungsplan",
    "28": "Verordnung bei Überweisung Soziotherapie",
    "36": "Empfehlung zur verhaltensbezogenen Primärprävention gem. § 20 Abs. 5 SGB V",
    "39": "Krebsfrüherkennung Zervix-Karzinom",
    "52": "Bericht für die Krankenkasse bei Fortbestehen der Arbeitsunfähigkeit",
    "55": "Bescheinigung einer schwerwiegenden chronischen Erkrankung gem. § 62 SGB V",
    "56": "Antrag auf Kostenübernahme",
    "61A": "Beratung zu medizinischer Rehabilitation / Prüfung des zuständigen Rehabilitationsträgers",
    "61B": "Verordnung von medizinischer Rehabilitation",
    "61C": "Verordnung von medizinischer Rehabilitation",
    "61D": "Verordnung von medizinischer Rehabilitation",
    "61E": "Verordnung von medizinischer Rehabilitation",
    "64": "Verordnung medizinischer Vorsorge für Mütter oder Väter gemäß § 24 SGB V",
    "65": "Ärztliches Attest Kind zur Verordnung einer medizinischen Vorsorge / Rehabilitation für Mütter oder "
          "Väter gemäß §§ 24, 41 SGB V",
}

# Muster 1a/E, version 09: chapter 3.1.1 of handbook version 4.59 (9 Dec 2020, the last one with Muster 1),
# archived at https://web.archive.org/web/20210513073618/https://www.kbv.de/media/sp/02a_Blankoformularbedruckung_Handbuch.pdf
# Version 4.60 raised the version of every form to extend the DMP codes; the field list stayed the same.
MUSTER_1 = (
    "Formularcode", "Formularcodeergänzung", "Versionsnummer", "Versicherungsschutz Ende", "Kostenträgerkennung",
    "Versicherten-ID", "Versichertenart", "Besondere Personengruppe", "DMP-Kennzeichnung",
    "(Neben-)Betriebsstättennummer", "LANR", "Ausstellungsdatum", "Erstbescheinigung", "Folgebescheinigung",
    "Arbeitsunfall", "Durchgangsarzt", "arbeitsunfähig seit", "voraussichtliche AU bis", "Festgestellt am",
    "Sonstiger Unfall", "BVG", "Rehabilitation", "Wiedereingliederung", "Sonstige Maßnahmen", "Krankengeldfall",
    "Endbescheinigung", "Diagnosen", "Hinweise zur Diagnose",
)

# Field tables from chapter 3, keyed by (form code, version). Muster 6/E, version 12: chapter 3.4.1 of 4.80.
FIELD_TABLES: dict[tuple[str, str], tuple[str, ...]] = {
    ("01", "09"): MUSTER_1,
    ("01", "10"): MUSTER_1,
    ("06", "12"): (
        "Formularcode", "Formularcodeergänzung", "Versionsnummer", "Anforderungs-Ident", "Nachname", "Vorname",
        "Geburtsdatum", "Versicherungsschutz Ende", "Kostenträgerkennung", "Kostenträgername",
        "WOP-Kennzeichen", "Versichertennummer", "Versichertenart", "Besondere Personengruppe",
        "DMP-Kennzeichnung", "(N)BSNR Überweiser", "Überweiser LANR", "Ausstellungsdatum", "Geschlecht", "Titel",
        "Namenszusatz", "Vorsatzwort", "PLZ", "Ort", "Straße", "Hausnummer", "Wohnsitzländercode",
        "PostfachPLZ", "PostfachOrt", "Postfach", "PostfachWohnsitzländercode",
        "Kurativ/Präventiv/bei belegärztl. Behandlung", "Unfall/Unfallfolgen", "OP-Datum", "Überweisung an",
        "AU bis", "Untersuchungsart", "Eingeschränkter Leistungsanspruch gemäß § 16 Abs. 3a SGB V",
        "Diagnose/Verdachtsdiagnose", "Befund/Medikation", "Auftrag",
    ),
}
DATE_FIELDS = {"Geburtsdatum", "Versicherungsschutz Ende", "Ausstellungsdatum", "OP-Datum", "AU bis",
               "arbeitsunfähig seit", "voraussichtliche AU bis", "Festgestellt am"}
# Muster 1 check boxes: "1 = angekreuzt".
CHECKBOX_FIELDS = ("Erstbescheinigung", "Folgebescheinigung", "Arbeitsunfall", "Durchgangsarzt", "Sonstiger Unfall",
                   "BVG", "Rehabilitation", "Wiedereingliederung", "Krankengeldfall", "Endbescheinigung")
CODED_FIELDS = {
    **{name: {"1": "ja"} for name in CHECKBOX_FIELDS},
    "Geschlecht": {"M": "männlich", "W": "weiblich", "X": "unbestimmt", "D": "divers"},
    "Kurativ/Präventiv/bei belegärztl. Behandlung": {"1": "kurativ", "2": "präventiv",
                                                     "4": "bei belegärztlicher Behandlung"},
    "Untersuchungsart": {"1": "Auftragsleistung", "2": "Konsiliaruntersuchung", "3": "Mit-/Weiterbehandlung"},
    "Unfall/Unfallfolgen": {"1": "ja"},
    "Eingeschränkter Leistungsanspruch gemäß § 16 Abs. 3a SGB V": {"1": "ja"},
}
DIAGNOSIS_FIELDS = {"Diagnose/Verdachtsdiagnose", "Diagnose", "Diagnosen"}
# ICD-10-GM code, then optional Diagnosesicherheit (G, V, Z, A) and Seitenlokalisation (R, L, B), each
# separated by a space (handbook chapter 2.5).
ICD_RE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,3})?[!†*+]?)(?: ([GVZA]))?(?: ([RLB]))?(?=[\s,;)]|$)")
SUFFIX_RE = re.compile(r"^([A-Z]*)([a-z]*)$")


def _iso(date: str) -> str | None:
    if re.fullmatch(r"\d{8}", date) and date != "00000000":
        return f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return None


def parse_icd10(text: str) -> list[dict]:
    return [{"code": code, "certainty": cert or None, "side": side or None}
            for code, cert, side in ICD_RE.findall(text)]


def match(data: bytes, aim: str | None = None) -> dict | None:
    if aim is not None and not aim.startswith("]L"):  # PDF417 only
        return None
    if b"\t" not in data:
        return None
    try:
        text = data.decode("iso-8859-15")
    except UnicodeDecodeError:
        return None
    fields = text.split("\t")
    if len(fields) < 4:
        return None
    code, suffix, version = fields[0], fields[1], fields[2]
    if not (re.fullmatch(r"\d{2}", code) and re.fullmatch(r"\d{2}", version)):
        return None
    if int(code) not in FORMS_WITH_BARCODE:
        return None
    m = SUFFIX_RE.match(suffix)
    if not m:
        return None
    variant, copy = m.groups()
    form = f"{int(code)}{variant}"

    result: dict = {
        "type": TYPE,
        "valid": True,
        "errors": [],
        "warnings": [],
        "form": form,
        "name": FORM_NAMES.get(form) or FORM_NAMES.get(str(int(code))),
        "copy": copy or None,
        "version": version,
        "field_count": len(fields),
        "note": "KBV Blankoformular barcode; not encrypted, usually contains health data",
        "specification": "https://update.kbv.de/ita-update/Blankoformulare/KBV_ITA_VGEX_Technisches_Handbuch_BFB.pdf",
    }
    table = FIELD_TABLES.get((code, version))
    if table is None:
        result["warnings"].append(f"no field table for Muster {form} version {version}; fields are not named")
        result["fields_raw"] = fields
        return result
    if len(fields) != len(table):
        result["valid"] = False
        result["errors"].append(f"{len(fields)} fields, Muster {form} version {version} has {len(table)}")
        result["fields_raw"] = fields
        return result

    named = {name: value for name, value in zip(table, fields) if value}
    decoded: dict = {}
    for name, value in named.items():
        if name in DATE_FIELDS:
            iso = _iso(value)
            if iso is None:
                result["warnings"].append(f"{name}: not a JJJJMMTT date: {value!r}")
            decoded[name] = iso
        elif name in CODED_FIELDS:
            meaning = CODED_FIELDS[name].get(value)
            if meaning is None:
                result["warnings"].append(f"{name}: unknown value {value!r}")
            decoded[name] = meaning
    result["fields"] = named
    result["decoded"] = decoded
    diagnoses = [d for name in DIAGNOSIS_FIELDS if name in named for d in parse_icd10(named[name])]
    if diagnoses:
        result["icd10"] = diagnoses
    return result
