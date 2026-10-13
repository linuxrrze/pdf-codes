# code-tools

Small Unix-style tools that pull facts out of PDFs and images: barcodes and QR codes, embedded files, and
ZUGFeRD / Factur-X / XRechnung e-invoices.

Every tool does one job and follows the same rules:
- It writes **JSON Lines** to stdout (`--text` for human-readable output) and diagnostics to stderr.
- It reads stdin when the file name is `-`.
- It uses **grep-style exit codes**: `0` found/valid, `1` not found/invalid, `2` usage error or unreadable input.
  `-q` prints nothing and only sets the exit code.

| Tool | Job |
|---|---|
| `code-scan` | Find and decode every QR code / barcode in PDFs **and images** (PNG, JPEG, TIFF, WebP, ...), anywhere on the page, and classify its payload |
| `code-parse` | Classify and parse barcode payloads from stdin (EPC, Swiss QR-bill, GS1, vCard, WiFi, URL, ...) |
| `pdf-attachments` | List or extract embedded files |
| `einvoice-info` | Detect ZUGFeRD / Factur-X / XRechnung: standard, profile, consistency warnings |
| `zugferd2xrechnung` | Extract the invoice XML (CII as embedded, or converted to UBL) |
| `xrechnung2zugferd` | Embed a CII XML into a PDF, or into an image of the invoice (scan, photo), producing a ZUGFeRD / Factur-X PDF/A-3 |
| `einvoice-validate` | Validate XML or PDF e-invoices with the KoSIT validator (XRechnung rules) |
| `code-tools-setup-java` | Download the Java components the last two need |

## Install

```sh
uv tool install .            # or: pipx install .   /   uv sync && uv run <tool>
```

Python 3.11+. Everything except validation and UBL conversion is pure Python plus wheels (pdfium, zxing-cpp, qpdf).

Optional extras:
- **Java 17+**, then run `code-tools-setup-java`. It downloads pinned, SHA-256-verified copies of the KoSIT
  validator 1.6.3, the XRechnung 3.0.2 validator configuration and phax `en16931-cii2ubl` 4.0.1 into
  `~/.cache/code-tools`. These are needed for `einvoice-validate` and `zugferd2xrechnung --syntax ubl`.
  Override the locations with `CODE_TOOLS_JAVA`, `CODE_TOOLS_KOSIT_JAR`, `CODE_TOOLS_XR_CONFIG` and `CODE_TOOLS_CII2UBL_JAR`.
  [docs/decisions/0001-optional-java-dependency.md](docs/decisions/0001-optional-java-dependency.md) explains
  why these two features use Java.
- **Ghostscript**, for `xrechnung2zugferd --pdfa-convert`.

## Examples

```sh
# Which PDFs in the inbox are e-invoices?
find inbox -name '*.pdf' -exec einvoice-info -q {} \; -print

# IBAN and amount of every payment QR code (EPC / GiroCode)
code-scan invoice.pdf | jq -r 'select(.payload.type=="epc") | "\(.payload.iban) \(.payload.amount)"'

# Just the content of the QR codes, nothing else
code-scan --raw --symbology qr doc.pdf

# Photos and scans work too; multi-page TIFFs are scanned page by page
code-scan receipt.jpg scan.tif

# Same, safe for multi-line payloads; parse later
code-scan --raw -0 doc.pdf | code-parse -0

# Extract the XRechnung, then validate it
zugferd2xrechnung rechnung.pdf | einvoice-validate -

# ... or as UBL for a recipient that only takes UBL
zugferd2xrechnung --syntax ubl rechnung.pdf -o rechnung-ubl.xml

# Turn a layout PDF plus an XRechnung (CII) into a ZUGFeRD PDF
xrechnung2zugferd layout.pdf invoice_uncefact.xml -o zugferd.pdf

# ... or a scanned invoice: each image page becomes a PDF/A page
xrechnung2zugferd scan.tif invoice_uncefact.xml -o zugferd.pdf
```

## How barcodes are found

Codes can be anywhere: in a corner or margin, rotated at any angle, inverted, tiny, drawn as vector paths,
embedded as images, inside form XObjects or annotations, or outside the visible crop area. `code-scan` runs
several passes and merges the results, so each code is reported once.

1. **Full page** at `--dpi` (300), rendered over the whole MediaBox with annotations and form fields included.
2. **Overlapping tiles** at `--tile-dpi` (600), for small codes. The tiles overlap by at least `--max-code-mm`
   (60 mm), so any code up to that size lies completely inside some tile.
3. **Embedded images** at their native resolution, including images nested in form XObjects.

Options:
- `--fast` runs only the first pass. It misses codes smaller than about 3 mm.
- `--thorough` adds a 1200 dpi tile pass and alternative binarisers for faded scans.

For images, `--dpi` is the resolution assumed when the file doesn't state one. Tiles are upscaled to
`--tile-dpi` relative to the image's resolution.

Each record contains:
- `bbox_pt` (PDFs): the code's position in PDF user space, in points, with page rotation removed;
- `bbox_px` (images): the code's position in pixels, origin top left, after EXIF rotation;
- `outside_cropbox`: whether the code lies outside the visible area;
- `source`: which passes found it.

Payload types include `epc`, `swiss_qr`, `gs1`, `iata_bcbp`, `kassensichv_receipt`, `uic_ticket`, `kbv_form`,
`pkv_invoice_code`, `deutsche_post_franking`,
`vcard`, `wifi`, `url` and more. [docs/formats.md](docs/formats.md) lists every recognised format with how far
it is decoded and a link to its specification.

How classification works:
- The first parser whose header matches decides the type, and then validates the structure (IBAN checksums,
  reference check digits, field layout).
- A damaged payment code is still reported as `epc` or `swiss_qr`, with `"valid": false` and a list of `errors`.
- Deviations from the standard that banks accept in practice don't make a code invalid. They go into
  `warnings` instead, e.g. an EPC amount with a decimal comma (`EUR482,57`).
- Payloads nothing recognises are reported as `raw`.

**`--raw` output.** Payloads are written byte for byte.
- One payload per line by default.
- `-0` separates payloads with NUL instead, which is safe for multi-line payloads.
- No separator can make payloads that contain NUL bytes unambiguous. `code-scan` warns on stderr when that
  happens; use `--save DIR` or the JSON `bytes_b64` field for those.

## How e-invoices are recognised

`einvoice-info` reads three independent signals and reports any disagreement between them as a warning:

1. **The embedded file:** its name and AFRelationship.
   - `factur-x.xml` (Factur-X / ZUGFeRD 2.1+)
   - `xrechnung.xml`
   - `zugferd-invoice.xml` (2.0)
   - `ZUGFeRD-invoice.xml` (1.0)
2. **The XMP metadata:** the ZUGFeRD/Factur-X extension schema (`ConformanceLevel` etc.) and the PDF/A identification.
3. **The XML itself:** its syntax (CII, ZUGFeRD 1.0 or UBL) and its specification identifier (BT-24). This one
   decides the profile:
   - MINIMUM, BASIC WL, BASIC, EN16931 or EXTENDED;
   - XRECHNUNG, with its version;
   - COMFORT for ZUGFeRD 1.0.

Filters:
- `--strict` accepts only complete EN 16931 invoices (BASIC and up).
- `--require-xrechnung` accepts only the XRECHNUNG profile.
- `--warnings-fail` treats any inconsistency as a mismatch.

## Creating ZUGFeRD files

`xrechnung2zugferd` writes the following:
- The XML, as an associated file (Names tree and catalog `/AF`, `AFRelationship` `Alternative` by default).
- XMP metadata:
  - PDF/A-3 identification;
  - the Factur-X properties, with `ConformanceLevel` taken from the XML (e.g. `XRECHNUNG`);
  - the PDF/A extension schema;
  - Info dictionary values synchronised into XMP;
  - Dublin Core values repaired.
- An sRGB output intent.

Before embedding, it checks the XML against the Factur-X XML schema for its profile.

Page content (fonts, colours) is not modified. If the input PDF is not PDF/A already, the tool warns. In that
case, use `--pdfa-convert` (Ghostscript) or create PDF/A-3 upstream.

Results checked with veraPDF:
- A PDF/A input passes PDF/A-3b after embedding.
- A non-PDF/A input passes after `--pdfa-convert`.

The attachment is named `factur-x.xml` for every profile, as in ZUGFeRD 2.2+. Use
`--attachment-name xrechnung.xml` for consumers of ZUGFeRD 2.1.1's XRECHNUNG profile.

## Development

```sh
uv sync
uv run python tests/fetch_fixtures.py   # ZUGFeRD corpus (pinned commit) + KoSIT XRechnung test suite
uv run pytest                           # tests needing missing fixtures, Java or Ghostscript are skipped
```

Test markers: `corpus` (downloaded fixtures), `java` (Java plus `code-tools-setup-java`), `slow`.
