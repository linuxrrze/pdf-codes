# Recognised formats

This page lists every format code-tools recognises, how far it decodes each one, and where its specification
is published. Specifications are linked, not copied, because most are licensed by their publishers.

How far a format is decoded:

| Level | Meaning |
|---|---|
| **full** | Every field defined by the specification is parsed and validated (checksums, value ranges). |
| **partial** | The specification is public, but only some fields or some variants are decoded. |
| **header** | Recognised by its documented header only. The content is encrypted or the layout is not public. |
| **inferred** | Fields were worked out by comparing samples with what is printed next to the code. Not official. |

## Barcode payloads (`code-scan`, `code-parse`)

The classifier tries the parsers below in order. The first one whose header matches decides the `type`
(`src/code_tools/codes/classify.py`). A damaged code keeps its type and gets `"valid": false` plus `errors`.
Deviations that are common in practice and harmless go into `warnings` instead. Anything that matches no
parser is `raw`.

| `type` | Format | Recognised by | Level | Specification |
|---|---|---|---|---|
| `epc` | EPC QR code ("GiroCode"), SEPA credit transfer | `BCD` header, version, charset, `SCT`/`INST` | full | EPC069-12, [European Payments Council](https://www.europeanpaymentscouncil.eu/document-library/guidance-documents/quick-response-code-guidelines-enable-data-capture-initiation) |
| `swiss_qr` | Swiss QR-bill (payment part) | `SPC` / `02xx` / `1` header | full | SIX Implementation Guidelines, [six-group.com](https://www.six-group.com/en/products-services/banking-services/payment-standardization/standards/qr-bill.html) |
| `emvco_mpm` | EMVCo merchant-presented QR code: PIX, PromptPay, PayNow, QRIS, VietQR and other instant-payment codes | `000201` + ID-length-value objects, `6304` + CRC-16 at the end | full; CRC checked | EMV QRCPS Merchant-Presented Mode 1.1, [EMVCo](https://www.emvco.com) (free registration) |
| `gs1` | GS1 element strings (GS1-128, GS1 DataMatrix/QR/DataBar/DotCode) | AIM identifier `]C1` `]d2` `]Q3` `]e0` `]J1`, or `(AI)…` text | partial | GS1 General Specifications, [gs1.org](https://www.gs1.org/standards/barcodes-epcrfid-id-keys/gs1-general-specifications) |
| `iso15434` | ISO/IEC 15434 envelope: IFA PPN / securPharm codes on German medicine packs, component labels, UPS MaxiCode | `[)>` RS + format + GS-separated fields | full for format 06 data identifiers and PPN; partial otherwise | ISO/IEC 15434 (not freely available); ANSI MH10.8.2 (MHI, free); IFA specification for securPharm codes |
| `uic_ticket` | Rail ticket (UIC 918.3), e.g. Deutsche Bahn online tickets | `#UT` + version, issuer, key ID | partial | UIC leaflet 918-3 (not freely available); layouts from [uic-918-3](https://github.com/justusjonas74/uic-918-3) (MIT) |
| `icao_vds` | ICAO Visible Digital Seal: visas, German arrival attestations, residence permits, address stickers, social insurance cards, administrative documents (Meldebescheinigung) | `0xDC`, version 0x02/0x03, C40 country code; DataMatrix | full for the profiles listed in the notes; signature not verified | ICAO Doc 9303 Part 13; [BSI TR-03137](https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/Standards-und-Zertifizierung/Technische-Richtlinien/TR-nach-Thema-sortiert/tr03137/tr-03137.html); profile tables cross-checked with [vdstools](https://github.com/tsenger/vdstools) |
| `eu_dcc` | EU Digital COVID Certificate | `HC1:` | header | [eu-dcc-hcert-spec](https://github.com/ehn-dcc-development/eu-dcc-hcert-spec) |
| `medication_plan` | Bundeseinheitlicher Medikationsplan (BMP) | `<MP` XML | header | [KBV: Medikationsplan](https://www.kbv.de/html/medikationsplan.php) |
| `deutsche_post_franking` | Deutsche Post franking mark ("Matrixcode") | `DEA` + binary data, DataMatrix | header; inferred for the 42-byte variant | [Deutsche Post: Matrixcode](https://www.deutschepost.de/de/f/frankierung/matrixcode.html), layout not public |
| `pkv_invoice_code` | eA/eP codes on private medical invoices (PKV, Beihilfe) | `eA`/`eP` + digit + base64-like text, DataMatrix | header (encrypted) | [lemniscus helpdesk](https://helpdesk.lemniscus.de/docs/rechnung-mit-ea-ep-codes), technical spec not public |
| `erezept` | E-Rezept token (German electronic prescription printout) | JSON `{"urls": ["Task/<ID>/$accept?ac=<code>"]}`, DataMatrix | full | gematik gemSpec_DM_eRp / gemSpec_FD_eRp; [prescription ID profile](https://gemspec.gematik.de/ig/fhir/ti/1.1.1/StructureDefinition-e-prescription-id.html) |
| `kbv_form` | KBV Blankoformular barcode on statutory medical forms ("Muster") | form number, page letters, version, TAB-separated, PDF417 | partial | [KBV Technisches Handbuch Blankoformularbedruckung](https://update.kbv.de/ita-update/Blankoformulare/KBV_ITA_VGEX_Technisches_Handbuch_BFB.pdf) |
| `iata_bcbp` | IATA Bar Coded Boarding Pass (boarding passes, e-ticket itinerary receipts) | `M` + number of legs, fixed-width fields, hex size fields | full (mandatory and conditional items) | IATA Resolution 792 (not freely available); [BCBP Implementation Guide](https://www.iata.org/contentassets/1dccc9ed041b4f3bbdcf8ee8682e75c4/2021_03_02-bcbp-implementation-guide-version-7-.pdf); field lengths from [bcbp](https://github.com/georgesmith46/bcbp) (MIT) |
| `kassensichv_receipt` | German cash-register receipt QR code (KassenSichV, TSE) | `V0;` + 12 fields separated by `;` | full; signature not verified | DSFinV-K 2.4, Anhang I, [Bundeszentralamt für Steuern](https://www.bzst.de/DE/Unternehmen/Aussenpruefungen/DigitaleSchnittstelleFinV/digitaleschnittstellefinv_node.html) |
| `rksv_receipt` | Austrian cash-register receipt QR code (RKSV) | `_R1-AT<n>_` + 13 fields separated by `_` | full; signature not verified | RKSV Anlage "Detailspezifikation", [RKSV](https://gesetzefinden.at/bundesrecht/verordnungen/rksv) |
| `dhl_return_label` | DHL return label QR code (sent by merchants for printer-free returns) | `RON\|` + 25 fields separated by `\|` | inferred; Identcode and Leitcode checked | not published; check digits: [paketda](https://www.paketda.de/firmenkunden/paket-pruefziffern.html), Leitcode layout: [ActiveBarcode](https://www.activebarcode.com/barcode/leitcode/) |
| `beihilfe_form` | QR code on Beihilfe applications and notices | `H001;` or `X_H001;` + form version `V MM.YYYY`, QR code | inferred | not published |
| `vcard` | vCard | `BEGIN:VCARD` | partial | [RFC 6350](https://www.rfc-editor.org/rfc/rfc6350) |
| `icalendar` | calendar event | `BEGIN:VEVENT` / `BEGIN:VCALENDAR` | partial | [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545) |
| `mecard` | MECARD contact | `MECARD:` | partial | de-facto, see [ZXing: Barcode Contents](https://github.com/zxing/zxing/wiki/Barcode-Contents) |
| `wifi` | Wi-Fi network | `WIFI:` | full | de-facto, see [ZXing: Barcode Contents](https://github.com/zxing/zxing/wiki/Barcode-Contents) |
| `otpauth` | one-time password setup (TOTP/HOTP), Google Authenticator export | `otpauth://`, `otpauth-migration://` | full | de-facto, [Key URI Format](https://github.com/google/google-authenticator/wiki/Key-Uri-Format) |
| `mailto` | e-mail link | `mailto:` | full | [RFC 6068](https://www.rfc-editor.org/rfc/rfc6068) |
| `tel` | phone number | `tel:` | full | [RFC 3966](https://www.rfc-editor.org/rfc/rfc3966) |
| `sms` | SMS | `sms:` / `SMSTO:` | full | [RFC 5724](https://www.rfc-editor.org/rfc/rfc5724), `SMSTO:` is de-facto |
| `geo` | geographic location | `geo:` | full | [RFC 5870](https://www.rfc-editor.org/rfc/rfc5870) |
| `url` | web link | `http://` / `https://` | full | [RFC 3986](https://www.rfc-editor.org/rfc/rfc3986) |

### Notes per format

**`epc`**
- Validates:
  - the IBAN checksum;
  - BIC format, with the BIC required in version 001;
  - the amount;
  - the purpose code;
  - the RF creditor reference checksum;
  - the 331-byte limit;
  - that a structured reference and unstructured text don't appear together.
- Accepts:
  - CRLF line endings;
  - character sets 1–8.
- Warnings:
  - **Decimal comma** (`EUR482,57`): the standard requires a point, but German banks accept codes with a
    comma and billing services produce them, so a comma is a warning, not an error.
  - Thousands separators and more than two decimal places are still errors.

**`swiss_qr`**
- Validates:
  - the 31–34 line layout and the reserved empty ultimate-creditor block;
  - CH/LI IBANs, including the QR-IBAN range 30000–31999;
  - the reference against the IBAN type: QR reference with recursive mod-10 check digit, RF creditor
    reference, or none;
  - currency and the `EPD` trailer.

**`gs1`**
- Splits element strings by the GS1 rules: predefined lengths and FNC1/GS separators.
- Checks the check digits of GTIN, SSCC and GLN.
- Converts dates (YYMMDD) and decimal measures (`310n` etc.).
- Names only the common application identifiers.

**`uic_ticket`**
- Container: `#UT`, version, issuer (RICS code, e.g. `0080` = Deutsche Bahn), key ID, signature (50 bytes for
  version 01, 64 for 02), then zlib-compressed records. Decompression is capped at 1 MB.
- Decoded records:
  - `U_HEAD`: issuer, order number, creation time, language.
  - `U_TLAY` ("RCT2"): the printed ticket text with line/column positions, e.g. stations, validity, route.
  - `0080BL` versions 02 and 03 (Deutsche Bahn): validity and serial number per order, plus the named S-blocks,
    e.g. traveller name, number of passengers, class.
- Other records (e.g. `U_FLEX`, the newer ASN.1 format) are listed with a warning, not decoded.
- The signature is **not verified**, so `signature_verified` is `null`. Verifying it needs the issuers' public keys
  from [railpublickey.uic.org](https://railpublickey.uic.org/).
- **Privacy:** tickets normally contain the traveller's name.

**`iata_bcbp`**
- Format "M" with any number of legs.
- Mandatory items per leg:
  - booking reference (PNR), from and to airports, carrier, flight number;
  - date of flight as day of year (the year is not encoded);
  - compartment, seat, check-in sequence number, passenger status.
- Conditional items, read via their hex size fields:
  - once per pass: version, passenger description, check-in and issuance source, date of issue (last digit of
    the year + day of year), document type, issuer, baggage tags;
  - per leg: ticket number (airline code + serial), selectee, marketing carrier, frequent-flyer airline and
    number, ID/AD, free baggage allowance, fast track;
  - per leg, the rest is kept as `airline_use`.
- Optional security data (`^`): its type and length are reported. The signature is not verified.
- `document_kind`: `B` = boarding pass, `I` = itinerary receipt. Itinerary receipts may leave the flight
  fields blank. Other codes (Resolution 792, Attachment C) are reported as-is, without a name.
- **Privacy:** passenger name, booking reference, frequent-flyer number.

**`kassensichv_receipt`**
- Twelve fields, split from both ends, because `processData` of `Bestellung-V1` may itself contain `;`:
  - QR version `V0`, till serial (client ID), process type, process data;
  - TSE transaction number, signature counter, start and finish times;
  - signature algorithm, time format, signature, public key.
- `tse_serial` is the SHA-256 of the public key, as Anhang I specifies.
- `Kassenbeleg-V1` is decoded into:
  - transaction type (e.g. `Beleg`);
  - gross sales per VAT rate: standard, reduced, the two §24 UStG average rates, 0 %;
  - payments: `Bar`/`Unbar`, with the currency when it isn't EUR.
- Gross sales and payments are compared when everything is paid in EUR. A mismatch is a warning.
- `Bestellung-V1` is decoded into its order items. Other process types keep their raw `process_data`.
- The TSE signature is **not verified**. Verifying it needs the TSE log message structure from BSI TR-03151.

**`dhl_return_label`**
- DHL publishes no specification. The fields were inferred from one label by comparing them with the printed
  addresses, so the record sits under `inferred` with a caveat.
- Confirmed by their check digits (weights 4 and 9 alternating, modulo 10):
  - the Identcode, the 12-digit parcel number, in fields 1 and 21;
  - the Leitcode in field 20: recipient postcode (5), street code (3), house number (3), product code (2,
    `33` = return), check digit. Its postcode is compared with the recipient's.
- Sender (the customer) is fields 5–10, recipient (the merchant's returns address) fields 11–16, each as name,
  second name line, street, postcode, city, country.
- Field 22 is a `YYMMDD` date, probably the expiry: in the sample it was 31 days after the letter, and DHL
  states the QR code is valid for up to 30 days. Fields 4, 23 and 24 are unknown and passed through.
- **Privacy:** contains both names and addresses.

**`beihilfe_form`**
- No specification is published. The layout was inferred from 13 documents from 2016 to 2021 (one code per
  page), so the fields sit under `inferred` with a caveat:
  `H001;V 10.2016;<UUID>;<page>;<8 digits>;<surname>;<first name>;`
- `H001` was on applications, `X_H001` on the office's notices (approvals, assessments).
- `V MM.YYYY` reads as the form version.
- The UUID was the same on every page of a document and differed between documents.
- The 8-digit number was the same in every document, so it is most likely the applicant's personnel number
  (`person_number`).
- An application on a 2013 form had only `H001;` and the form version; it is recognised too.
- **Privacy:** contains the applicant's name and number.

**`deutsche_post_franking`**
- `DEA` = DE (Germany) + A (Deutsche Post), as documented by Deutsche Post. The rest of the layout is not
  published; Deutsche Post's own DataMatrixCodeChecker reads it.
- For the 42-byte layout, these fields were inferred and appear under `inferred`. The source was 13 letters
  from 2011 to 2026 by several senders, compared with the text printed next to the code:

  | Bytes | Field |
  |---|---|
  | 4 | rises over time (`19` in 2011 … `3b` in 2026), presumably a format or key version (`version_byte`) |
  | 10–11 | postage in cents |
  | 12–13 | mailing date as DDDYY (day of year × 100 + year) |
  | 17–18 | the middle number of the printed line `*…*NNNN*…*` |
  | 19–21 | the start of the printed hex line |
  | 22–41 | varies by sender: zeros; or a run of ASCII digits (`sender_reference`); or spaces, then `A c4 02` and four further bytes |

- The postage matched Deutsche Post's official rate at the decoded mailing date on every letter:
  - 0.55 € in 2011;
  - 0.70 € from 2016 until June 2019;
  - 0.80 € from July 2019;
  - 0.85 € for the Kompaktbrief (2016–2019), and for the Standardbrief from 2022;
  - 0.95 € in 2026.
- In the `A c4 02` layout, the last four bytes match no standard CRC-16/CRC-32, sum or truncated hash, and no
  CRC-16 polynomial at all. Presumably they are the cryptographic signature.

**`pkv_invoice_code`**
- An industry scheme of private health insurers and Beihilfe offices.
- **eA** ("elektronischer Abrechnungscode", top right of the invoice) holds personal data: recipient's
  address, patient's date of birth.
- **eP** ("elektronischer Positionscode", bottom left) holds the invoice data without personal data.
- Both are encrypted and only decodable by the insurers' and Beihilfe apps.
- Observed plain parts of eP: `eP` + 8 digits + base64 (16 bytes) + 1 digit + base64 (32 bytes) + 10 digits.
  The last 4 digits matched the invoice counter of the billing centre's account number in two samples.
  This observation is not used by the parser.
- An older eP layout with `_` separators turned up on lab invoices from 2018 and 2019: `eP` + 18 digits +
  `_1_au_` + 9 digits (the first six read as a YYMMDD date one to two weeks before the invoice) + base64
  (32 bytes) + 10 digits. It is recognised the same way.

**`kbv_form`**
- Every form starts with:
  - the form code (Muster number, 2 digits);
  - the form-code extension: upper-case letters mark the variant (e.g. `10` + `A` = Muster 10A), lower-case
    letters the copy or page;
  - the barcode version.
- Recognised for every form that has a barcode table in the handbook.
- Official form names come from the `DN` attribute of the KBV
  [Ausfüllhilfe](https://update.kbv.de/ita-update/Blankoformulare/Ausfuellhilfe.zip) XML files.
- Field names are decoded for:
  - **Muster 6 (Überweisungsschein), version 12**, the table in chapter 3.4.1 of handbook version 4.80;
  - **Muster 1 (Arbeitsunfähigkeitsbescheinigung), versions 09 and 10**, the table in chapter 3.1.1 of
    version 4.59 ([archived copy](https://web.archive.org/web/20210513073618/https://www.kbv.de/media/sp/02a_Blankoformularbedruckung_Handbuch.pdf)).
    Version 4.60 raised every form's version for new DMP codes without changing this table. Version 4.61 (August
    2021) dropped Muster 1 when the electronic AU certificate (eAU) arrived, but AU printouts with the barcode
    still turn up.

  Decoding includes:
  - dates converted to ISO format;
  - coded values the handbook defines (sex, curative/preventive, type of examination, Muster 1 check boxes);
  - ICD-10-GM codes with certainty (G/V/Z/A) and side (R/L/B) extracted.
- Other forms and versions are reported with their raw fields and a warning. Adding one means copying its
  table from chapter 3 into `FIELD_TABLES` in `src/code_tools/codes/parsers/kbv.py`.
- **Privacy:** the barcode is not encrypted and normally contains health data: diagnoses, insurer, date of
  birth, address.

**`emvco_mpm`**
- Splits the ID-length-value objects and checks that they cover the whole payload, that the CRC (ID 63) comes
  last, and its CRC-16/CCITT-FALSE value.
- Names the card networks of IDs 02-25 and the payment scheme of templates 26-51 by their globally unique
  identifier (sub-ID 00), e.g. `br.gov.bcb.pix` = PIX. Unknown schemes keep their identifier.
- Decodes merchant category, currency (ISO 4217 numeric to code), amount, tip and fees, country, merchant name
  and city, the additional data template (62) and the alternate-language template (64).
- Missing mandatory fields (52, 53, 58, 59, 60) are warnings: some national variants leave them out.

**`iso15434`**
- Splits the envelopes by RS and their fields by GS. A DataMatrix "Macro 05/06" is expanded by the decoder.
- Format 06: each field is a data identifier (up to three digits and a letter) and a value; common identifiers
  are named.
- With a PPN (`9N`), a `pharma` block holds PPN, PZN, batch (`1T`), expiry (`D`, day `00` = end of month),
  serial number (`S`) and GTIN (`8P`). The PPN check digits (mod 97 over ASCII values weighted from 2), the PZN
  check digit (mod 11) and the GTIN check digit are validated. A PPN without batch, expiry or serial is a
  warning.
- Format 05 is split with the GS1 rules. Other formats keep their fields as they are.

**`icao_vds`**
- Header: version (0x02 = version 3, 0x03 = version 4), issuing country, signer, certificate reference, issue
  and signature date, document type. When the version byte does not match the header layout (some arrival
  attestations), the other layout is used and a warning is added.
- Features are decoded for: visa and emergency travel document (ICAO), arrival attestation (Ankunftsnachweis),
  residence permit and its supplementary sheet, address stickers for ID card and residence permit card, place
  of residence sticker for passports, social insurance card, and administrative documents (BSI TR-03171) with
  the Meldebescheinigung profile. MRZs come as two lines.
- Unknown document types and tags are listed with their bytes and, where they decode, as C40 or UTF-8 text.
- The signature is not verified; `signature_length` gives its size. The newer ICAO IDB barcodes (`RDB...`)
  are a different format and are not recognised.
- **Privacy:** most seals hold the holder's name, date of birth, document numbers or address.

**`erezept`**
- Decodes each token: prescription ID, flow type (160, 162, 169, 200, 209 are named) and access code.
- Validates the ID's check digits (ISO 7064 Mod 97-10) and the 64-hex-digit access code. Unknown flow types and
  more than three tokens are warnings.
- **Privacy:** the ID and access code are all a pharmacy needs to redeem the prescription. Treat the code like
  the prescription itself.

**`rksv_receipt`**
- Decodes algorithm, trust service provider, cash register ID, receipt number, date and time, the gross amounts
  per VAT rate (20 %, 10 %, 13 %, 0 %, 19 %) and their total.
- Recognises cancellation (`STO`) and training (`TRA`) receipts and a failed signature device
  ("Sicherheitseinrichtung ausgefallen", a warning).
- Checks the formats of date, amounts and the base64 fields. The signature is not verified, because the
  certificate is not part of the code.

**`icalendar`**
- Reads every `VEVENT`: summary, start, end, location, description, URL, organiser, UID and repeat rule.
  Dates become ISO; a local time with `TZID` keeps the zone name in brackets.
- A missing `END:VEVENT` or `DTSTART` is an error.

**`otpauth`**
- Key URI: type, issuer, account, secret, algorithm, digits, period and counter. Checks that the secret is
  base32 and that HOTP has a counter. An issuer parameter that differs from the label prefix is a warning.
- Migration export: decodes the protobuf payload into its accounts (secret as base32, name, issuer, type,
  algorithm, digits, counter) and the batch information.
- **Privacy:** the secret lets anyone generate the one-time passwords. A migration export holds every exported
  account.

### Symbologies

Decoding is done by [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp), which reads:
- 2-D codes: QR, Micro QR, rMQR, DataMatrix, Aztec, PDF417, MaxiCode;
- linear codes: the EAN/UPC family, Code 39/93/128, Codabar, ITF, DataBar and DX film edge.

The `symbology_identifier` field is the AIM symbology identifier (ISO/IEC 15424, not freely available). Its
modifier tells, for example, GS1 content (`]C1`, `]d2`, `]Q3`) apart from plain content.

## E-invoices (`einvoice-info`, `zugferd2xrechnung`, `xrechnung2zugferd`, `einvoice-validate`)

| Format | What code-tools does | Specification |
|---|---|---|
| ZUGFeRD 1.0, 2.0, 2.1+ | detect (attachment, XMP, profile), extract | [FeRD: ZUGFeRD](https://www.ferd-net.de/standards/zugferd) |
| Factur-X | same as ZUGFeRD 2.1+, which is technically identical | [FNFE-MPE: Factur-X](https://fnfe-mpe.org/factur-x/) |
| XRechnung (CII and UBL) | detect, extract, validate, convert CII→UBL, embed CII | [XRechnung (KoSIT)](https://xeinkauf.de/xrechnung/) |
| EN 16931 (semantic model, CII D16B / UBL 2.1 syntaxes) | profile detection, validation via KoSIT | EN 16931-1 (CEN, not freely available) |
| PDF/A-3 | XMP identification, associated files, output intent | ISO 19005-3 (not freely available), checked with [veraPDF](https://verapdf.org) |

Tools and test data used:
- [KoSIT validator](https://github.com/itplr-kosit/validator) and its
  [XRechnung configuration](https://github.com/itplr-kosit/validator-configuration-xrechnung);
- [phax en16931-cii2ubl](https://github.com/phax/en16931-cii2ubl);
- [ZUGFeRD corpus](https://github.com/ZUGFeRD/corpus) and the
  [XRechnung test suite](https://github.com/itplr-kosit/xrechnung-testsuite).

[docs/decisions/0001-optional-java-dependency.md](decisions/0001-optional-java-dependency.md) explains why
validation and conversion use Java.

## Adding a format

[adding-a-parser.md](adding-a-parser.md) explains how to write, register, test and document a parser, and how to
bring saved scan results up to date with `code-reparse`.
