# Adding a payload parser

This guide covers how to teach `code-scan` and `code-parse` a new barcode payload format, and how to bring
existing scan results up to date afterwards. [formats.md](formats.md) lists the formats that exist already.

## How classification works

`code-scan` decodes a code into bytes and passes them, together with the AIM symbology identifier, to
`classify()` in `src/code_tools/codes/classify.py`. That function asks each parser in the `PARSERS` list in
turn. The first parser that returns a dict decides the payload's `type`. If every parser returns `None`, the
payload is `raw`.

So a parser has two jobs:
1. **Decide whether the payload is its format.** Return `None` if not. Be strict: a false positive hides the
   payload from every parser after it.
2. **Once it is sure, always claim the payload.** A damaged code of a known format is reported with
   `"valid": false` and `errors`, not dropped back to `raw`.

## 1. Write the parser

Give a format with more than a few lines of logic its own module in `src/code_tools/codes/parsers/` (for
example `dhl.py` or `kassensichv.py`). Short header-only checks can go into `generic.py`.

The signature is always:

```python
def match(data: bytes, aim: str | None = None) -> dict | None:
```

- `data` is the decoded payload as bytes, exactly as in the code.
- `aim` is the [AIM symbology identifier](#aim-symbology-identifiers), for example `]Q1` for a QR code. It is
  `None` when the payload comes from `code-parse` without `--aim`, so never require it. Use it only to rule
  out a symbology that the format does not allow.
- **Never raise.** Catch your own parsing errors and report them in `errors`. As a safety net, `classify()`
  catches a crash and reports the payload as `raw` with `"valid": false` and the error
  `internal error in the <name> parser: ...`, without trying the remaining parsers. The scan goes on, but the
  payload is lost to its real type, so treat that error as a bug.

### The module docstring

State where the layout comes from:
- for a published format, the specification's name, version, chapter and a link;
- for an unpublished one, how the layout was inferred: how many samples, from which years, compared with
  what. Say which claims are confirmed (for example by check digits) and which are guesses.

### Recognising the format

- Check the header first and return `None` as early as possible. Most payloads belong to other formats.
- A short header is not enough on its own. `H001;` alone could be anything, so `beihilfe.py` also requires a
  form version in the second field. `kbv.py` checks the form number against the list of known forms.
- Decode text explicitly. Use the encoding the specification prescribes (`kbv.py` uses ISO 8859-15).
  Without one, try UTF-8 and fall back to ISO 8859-1, as `dhl.py` and `beihilfe.py` do.
  `common.decode_text()` returns `None` instead of raising.

### The result

```python
{
    "type": "dhl_return_label",   # the name registered in PARSERS
    "valid": True,                # False whenever errors is not empty
    "errors": [],                 # the payload breaks the format: bad check digit, missing field, ...
    "warnings": [],               # odd but usable: unexpected field count, unknown code value, ...
    "note": "contains the names and addresses of sender and recipient",
    ...                           # the decoded fields
}
```

- **`type`, `valid`, `errors` and `warnings`** are always present. `classify()` puts them first and fills in an
  empty `warnings` list if the parser left it out, but set all four yourself so the parser reads clearly.
- **Errors or warnings?** Use an error when a check the specification defines fails, or when the structure
  cannot be read. Use a warning for deviations that are common in practice and harmless. The decimal comma in
  EPC amounts is one example: banks accept it, so it is a warning.
- **Field names** are English `snake_case`, except where the specification names its fields. There the
  official names are kept, as in the KBV forms.
- **Normalise values** that have an obvious canonical form: dates to ISO `YYYY-MM-DD`, amounts to strings
  with a dot, numbers that are numbers to `int`. Keep identifiers that may have leading zeros as strings.
- **Leave out empty fields** instead of writing `""` or `None`, unless the absence itself is information.
- **Keep it JSON-safe:** `str`, `int`, `float`, `bool`, `None`, `list` and `dict` only. Format `Decimal`
  values as strings.
- **`note`** is for privacy hints, such as "contains health data" or "contains the passenger's name". Add one
  whenever the payload holds personal data.
- **`specification`** may link the document the fields come from.

### Inferred formats

When a layout was worked out from samples rather than a specification, put every field whose meaning was
inferred under `inferred`, and end that dict with a `caveat`:

```python
result["inferred"] = {
    "identcode": "...",
    "date": "2026-01-31",
    "unknown_fields": {"4": "A"},   # pass through what is not understood, keyed by position
    "caveat": "inferred from one label by comparison with the printed addresses; not an official decoding",
}
```

- Validate whatever can be validated: check digits, dates, values that must match a printed field.
- Name a field only as confidently as the evidence allows. If the evidence is weak, say so in the docstring
  and in formats.md, or use a neutral name. `beihilfe.py` calls its field `person_number` and only says it
  is "most likely" the personnel number.

### Shared helpers

`src/code_tools/codes/parsers/common.py` has:
- `iban_valid()`, `rf_reference_valid()` and `BIC_RE` for payment data;
- `decode_text()`;
- `split_lines()`, which splits on CRLF or LF and keeps spaces.

Add a helper there when a second parser needs it.

## 2. Register it

Add the parser to `PARSERS` in `src/code_tools/codes/classify.py`, using the same name as its `type`:

```python
from .parsers import bcbp, beihilfe, dhl, ...

PARSERS = [
    ...
    ("dhl_return_label", dhl.match),
    ...
]
```

**Order matters.** The first parser that returns a dict wins. Put formats with a distinctive header before
generic ones: everything specific goes before `vcard`, `wifi` and the other generic types, and `url` stays
last because almost anything can start with a scheme. If two formats can match the same payload, put the
stricter one first and add a test that the other one is not misread.

## 3. Test it

Put the tests in `tests/test_<format>.py`, or in `tests/test_parsers.py` for a small header check.

**Use invented data only.** Real codes contain names, addresses, insurance numbers or health data. Build
payloads from obviously fake values like `Erika Mustermann` and `12345678`, and compute valid check digits
instead of copying real numbers. Never paste a real code into a test, not even a partly edited one.

Cover at least:
- **a complete, valid payload**, checking the decoded fields and that `warnings` is empty;
- **each error and warning** the parser can report, with `valid` false for errors;
- **look-alikes that must not match**: the header alone, a similar prefix (`RONALD|` against `RON|`),
  the header in the middle of text, and a symbology the format does not allow. Use `pytest.mark.parametrize`
  over a list of payloads;
- **the encodings** the format allows, for example an umlaut in ISO 8859-1;
- **every version or variant** you know of.

`classify(payload, "]Q1")` tests the parser through the classifier, including its position in `PARSERS`.
To test the whole path, from a code in a document to the payload, `tests/pdfgen.py` draws QR codes and
other symbologies into PDFs and images. `tests/test_images.py` shows how.

Run the tests with:

```sh
uv run pytest -q
```

## 4. Check it against real scan results

Keep real documents and scan results outside the repository. If you scanned your own documents with
`code-scan` into JSON Lines files, `code-reparse` shows what the new parser changes, without scanning again:

```sh
code-reparse --summary --changed results/*.jsonl > changed.jsonl
```

- The summary on stderr counts the changed payloads by old and new type, for example
  `28  raw -> beihilfe_form`.
- An unexpected transition, such as `url -> your_type` or a drop in recognised codes of another type,
  usually means the header check is too loose or the parser is in the wrong position in `PARSERS`.
- Look at `changed.jsonl` for `"valid": false` and warnings on real codes. A warning on most real samples
  means the parser is too strict.

Then check that nothing real ended up in the repository, for example by grepping `src`, `tests` and `docs`
for the IDs and numbers in your samples.

## 5. Document it

- **The parser module's docstring** says where the layout comes from (see above).
- **[formats.md](formats.md):**
  - add a row to the table in "Barcode payloads", in the same position as in `PARSERS`. Give the decoding
    level (full, partial, header or inferred, defined at the top of that page) and a link to the
    specification, or "not published". A `|` inside a table cell must be escaped as `\|`, even within
    backticks;
  - add a notes section with what is decoded, what is not, how inferred fields were confirmed, and a
    **Privacy** line if the payload holds personal data.
- **[README.md](../README.md):** add the type to the list of payload types.

## 6. Bring existing scan results up to date

`code-reparse` rebuilds every record's `payload` from its `bytes_b64` and `symbology_identifier`. All other
fields stay as they are.

```sh
code-reparse --summary --in-place results/*.jsonl
```

- **Without `--in-place`**, the updated records go to stdout. `--changed` prints only records whose
  payload changed.
- **With `--in-place`**, each file that has a changed payload is replaced atomically. Unchanged files are not
  touched.
- **Files still being written are protected.** `--in-place` skips files modified in the last 60 seconds
  (`--min-age`), and it leaves alone a file that changed while it was being read. So a scan that is still
  running can keep writing into the same directory.
- Lines that are not code-scan records, such as a half-written last line, are kept as they are, with a
  warning.
- The exit status is 0 if any payload changed and 1 if none did.

Re-scanning is only needed when the scanner itself changes, for example to find codes it missed before.

## AIM symbology identifiers

zxing-cpp reports the identifier as `]` + a letter for the symbology + a modifier digit. The letter is
enough to restrict a format to a symbology:

| Prefix | Symbology |
|---|---|
| `]Q` | QR code, Micro QR (`]Q3`: GS1 QR) |
| `]d` | DataMatrix (`]d2`: GS1 DataMatrix) |
| `]L` | PDF417 |
| `]z` | Aztec |
| `]C` | Code 128 (`]C1`: GS1-128) |
| `]A` | Code 39 |
| `]I` | Interleaved 2 of 5 (ITF) |
| `]E` | EAN / UPC |

Write the check so that `aim is None` passes:

```python
if aim is not None and not aim.startswith("]Q"):  # QR code only
    return None
```

## Checklist

- [ ] Parser returns `None` unless the format is certain, never raises, and returns `type`, `valid`,
      `errors`, `warnings`.
- [ ] Inferred fields sit under `inferred` with a `caveat`; personal data is flagged in `note`.
- [ ] Registered in `PARSERS` under its `type`, before any more generic parser.
- [ ] Tests with invented data cover the valid case, every error, look-alikes and variants. `uv run pytest`
      passes.
- [ ] `code-reparse --summary --changed` over real scan results shows only the expected transitions.
- [ ] No real values in `src`, `tests` or `docs`.
- [ ] Docstring, formats.md (table row and notes) and the README list are updated.
