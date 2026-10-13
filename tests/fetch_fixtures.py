"""Download test fixtures that are too large or too foreign to keep in the repository.

    uv run python tests/fetch_fixtures.py

Files go to tests/fixtures/corpus/ (ZUGFeRD corpus, Apache-2.0, pinned commit) and
tests/fixtures/xrechnung-testsuite/ (KoSIT XRechnung test suite, pinned release).
Tests that need them are marked ``corpus`` and skip when the files are missing.
"""

from __future__ import annotations

import io
import pathlib
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).parent / "fixtures"

CORPUS_COMMIT = "d891458e9822e34271a5438497bf924e89955979"
CORPUS_BASE = f"https://raw.githubusercontent.com/ZUGFeRD/corpus/{CORPUS_COMMIT}/"
CORPUS_FILES = [
    "ZUGFeRDv1/correct/Intarsys/ZUGFeRD_1p0_BASIC_Einfach.pdf",
    "ZUGFeRDv1/correct/Intarsys/ZUGFeRD_1p0_COMFORT_Einfach.pdf",
    "ZUGFeRDv1/correct/Intarsys/ZUGFeRD_1p0_EXTENDED_Warenrechnung.pdf",
    "ZUGFeRDv2/correct/intarsys/MINIMUM/zugferd_2p0_MINIMUM.pdf",
    "ZUGFeRDv2/correct/intarsys/BASIC/zugferd_2p0_BASIC_Einfach.pdf",
    "ZUGFeRDv2/correct/intarsys/EN16931/zugferd_2p0_EN16931_Einfach.pdf",
    "ZUGFeRDv2/correct/intarsys/EXTENDED/zugferd_2p0_EXTENDED_Warenrechnung.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/MINIMUM/zugferd_2p1_MINIMUM_Rechnung.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/BASIC WL/zugferd_2p1_BASIC-WL_Einfach.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/BASIC/zugferd_2p1_BASIC_Einfach.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/EN16931/zugferd_2p1_EN16931_Einfach.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/EN16931/zugferd_2p1_EN16931_Elektron_XRechnung.pdf",
    "ZUGFeRDv2/correct/symtrax/Beispiele/EXTENDED/zugferd_2p1_EXTENDED_Warenrechnung.pdf",
    "ZUGFeRDv2/correct/FNFE-factur-x-examples/Facture_FR_BASICWL.pdf",
    "XML-Rechnung/FX/EN16931_Einfach.pdf",
    "XML-Rechnung/FX/XRECHNUNG_Einfach.pdf",
    "XML-Rechnung/FX/XRECHNUNG_Elektron.pdf",
    "ZUGFeRDv2/fail/Mustangproject/wrongFilename.pdf",
    "ZUGFeRDv2/fail/FX-With-UBL-REC50304330.pdf",
    "ZUGFeRDv2/fail/MustangRE-20171118_506_ZUGFeRD1and2.pdf",
    "unstructured/RE-E-974-Hetzner_2016-01-19_R0005532486.pdf",
]

TESTSUITE_URL = ("https://github.com/itplr-kosit/xrechnung-testsuite/releases/download/"
                 "v2026-08-31/xrechnung-3.0.2-testsuite-2026-08-31.zip")


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url.replace(" ", "%20"), timeout=60) as resp:
        return resp.read()


def main() -> None:
    corpus = HERE / "corpus"
    for rel in CORPUS_FILES:
        dest = corpus / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print("fetch", rel)
        dest.write_bytes(fetch(CORPUS_BASE + rel))

    suite = HERE / "xrechnung-testsuite"
    if not suite.exists():
        print("fetch", TESTSUITE_URL)
        with zipfile.ZipFile(io.BytesIO(fetch(TESTSUITE_URL))) as zf:
            for member in zf.infolist():
                target = (suite / member.filename).resolve()
                if not target.is_relative_to(suite.resolve()):
                    raise SystemExit(f"refusing unsafe zip member {member.filename!r}")
                if member.is_dir():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))


if __name__ == "__main__":
    main()
