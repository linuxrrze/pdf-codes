# 1. Optional Java dependency for validation and UBL conversion

- Status: accepted
- Date: 2026-10-13

## Context

code-tools is Python. Two features have no Python implementation of reference quality:

1. **Validating e-invoices against the XRechnung rules** (`einvoice-validate`). The EN 16931 and XRechnung
   business rules (e.g. BR-DE-15, "Buyer reference must be present") are published as Schematron compiled to
   XSLT 2.0. lxml only supports XSLT 1.0, so they cannot run in plain Python. The official tool that runs them
   is the KoSIT validator, a Java application. German public-sector invoice portals use the same validator.
2. **Converting CII to UBL** (`zugferd2xrechnung --syntax ubl`). ZUGFeRD can only embed CII, but some
   recipients accept only UBL.

## Options considered

### Validation

| Option | Result |
|---|---|
| KoSIT validator 1.6.3 + XRechnung 3.0.2 configuration (Java) | The reference implementation; verdicts match what recipients' portals report |
| `saxonche` (Saxon XSLT engine as a Python wheel, no JVM) running the configuration's Schematron XSLs, plus lxml for the XML schema | Not tested. Would require re-implementing KoSIT's scenario selection and report, so results would no longer be guaranteed identical to the reference |

### CII → UBL conversion

| Option | Result on the 41 CII invoices of the KoSIT XRechnung test suite |
|---|---|
| `factur-x` 7.6 (Python): `parse_ubl_cii_xml` + `generate_ubl_xml` | 27 of 41 converted. Failures on common cases: multiple payment means (BT-81), order references, a missing optional field. Rejects XRechnung URNs unless the level is forced. Adds a Peppol `ProfileID` that is not in the source |
| phax `en16931-cii2ubl` 4.0.1 (Java, Apache-2.0) | 41 of 41 converted. Every result passes the KoSIT validator. Keeps the XRechnung `CustomizationID` |

A converter that silently drops or invents invoice data is worse than none, so the Python option was rejected.

## Decision

Use the Java tools for these two features only, and keep Java **optional**:

- Barcodes, attachments, e-invoice detection, CII extraction and ZUGFeRD embedding do not need Java.
- `code-tools-setup-java` downloads pinned versions with SHA-256 checksums into `~/.cache/code-tools`:
  - KoSIT validator 1.6.3;
  - XRechnung 3.0.2 validator configuration 2026-08-31;
  - en16931-cii2ubl 4.0.1.

  Pins and checksums live in `src/code_tools/einvoice/java.py`.
- Each location can be overridden: `CODE_TOOLS_JAVA`, `CODE_TOOLS_KOSIT_JAR`, `CODE_TOOLS_XR_CONFIG`,
  `CODE_TOOLS_CII2UBL_JAR`.
- Without Java, the two features fail with exit code 2 and a message that says what to install. The tests
  marked `java` are skipped.

## Consequences

- Users who need validation or UBL output must install Java 17+.
- The Java tools start a JVM for each call, about 3–5 s, which makes batch validation slow.
- Gotcha: the converter exits with status 0 even when conversion fails. The wrapper in
  `src/code_tools/einvoice/convert.py` treats the missing output file as the error and collects the `[ERROR]` lines.
- New XRechnung releases need the configuration pin and checksum to be updated.

## Revisit when

- A Java-free validator is wanted. Prototype the `saxonche` route and accept it only if it gives the same
  verdict and rule codes as KoSIT on the whole XRechnung test suite.
- A Python CII→UBL converter converts all 41 test-suite invoices to UBL that passes KoSIT validation.
- Batch throughput matters: run KoSIT in daemon mode (`-D`) instead of one JVM per file.
