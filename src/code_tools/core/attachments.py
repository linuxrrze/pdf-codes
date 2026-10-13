"""Find embedded files in a PDF.

Files can be attached in three places, and ZUGFeRD files typically use the first two at once:
the document's EmbeddedFiles name tree, the associated-files (/AF) arrays of the catalog and pages,
and FileAttachment annotations on pages. Each file specification is reported once.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

import pikepdf

DEFAULT_MAX_ATTACHMENT_BYTES = 256 * 1024 * 1024


@dataclass
class Attachment:
    name: str
    filespec: pikepdf.Dictionary = field(repr=False)
    sources: list[str] = field(default_factory=list)
    page: int | None = None  # 1-based, for annotation attachments
    description: str | None = None
    afrelationship: str | None = None
    mime_type: str | None = None
    declared_size: int | None = None
    created: str | None = None
    modified: str | None = None

    def stream(self) -> pikepdf.Stream | None:
        ef = self.filespec.get("/EF")
        if not isinstance(ef, pikepdf.Dictionary):
            return None
        for key in ("/UF", "/F", "/DOS", "/Unix", "/Mac"):
            stream = ef.get(key)
            if isinstance(stream, pikepdf.Stream):
                return stream
        return None

    def read(self, max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES) -> bytes:
        stream = self.stream()
        if stream is None:
            raise ValueError(f"attachment {self.name!r} has no embedded data")
        length = stream.get("/Length")
        if isinstance(length, int) and length > max_bytes:
            raise ValueError(f"attachment {self.name!r} is larger than {max_bytes} bytes")
        data = stream.read_bytes()
        if len(data) > max_bytes:
            raise ValueError(f"attachment {self.name!r} is larger than {max_bytes} bytes")
        return data

    def to_record(self, data: bytes | None = None) -> dict:
        record = {
            "name": self.name,
            "safe_name": safe_filename(self.name),
            "size": len(data) if data is not None else self.declared_size,
            "mime_type": self.mime_type,
            "description": self.description,
            "afrelationship": self.afrelationship,
            "sources": self.sources,
            "page": self.page,
            "created": self.created,
            "modified": self.modified,
        }
        if data is not None:
            record["sha256"] = hashlib.sha256(data).hexdigest()
        return record


def _text(obj) -> str | None:
    if obj is None:
        return None
    try:
        return str(obj)
    except Exception:  # undecodable string object
        return None


def _name(obj) -> str | None:
    if isinstance(obj, pikepdf.Name):
        return str(obj)[1:]
    return None


def _filespec_name(filespec: pikepdf.Dictionary, fallback: str | None) -> str:
    for key in ("/UF", "/F", "/DOS", "/Unix", "/Mac"):
        value = filespec.get(key)
        if isinstance(value, pikepdf.String):
            text = _text(value)
            if text:
                return text
    return fallback or "unnamed"


def _key(obj: pikepdf.Object):
    return obj.objgen if obj.is_indirect else id(obj)


def _describe(filespec: pikepdf.Dictionary, tree_name: str | None) -> Attachment:
    att = Attachment(name=_filespec_name(filespec, tree_name), filespec=filespec)
    att.description = _text(filespec.get("/Desc"))
    att.afrelationship = _name(filespec.get("/AFRelationship"))
    stream = att.stream()
    if stream is not None:
        subtype = _name(stream.get("/Subtype"))
        att.mime_type = subtype.replace("#2F", "/") if subtype else None
        params = stream.get("/Params")
        if isinstance(params, pikepdf.Dictionary):
            size = params.get("/Size")
            att.declared_size = int(size) if isinstance(size, int) else None
            att.created = _text(params.get("/CreationDate"))
            att.modified = _text(params.get("/ModDate"))
    return att


def _iter_name_tree(node: pikepdf.Object, depth: int = 0):
    """Yield (name, value) pairs of a PDF name tree, guarding against cycles and deep nesting."""
    if depth > 32 or not isinstance(node, pikepdf.Dictionary):
        return
    names = node.get("/Names")
    if isinstance(names, pikepdf.Array):
        for i in range(0, len(names) - 1, 2):
            yield _text(names[i]), names[i + 1]
    kids = node.get("/Kids")
    if isinstance(kids, pikepdf.Array):
        for kid in kids:
            yield from _iter_name_tree(kid, depth + 1)


def find_attachments(pdf: pikepdf.Pdf) -> list[Attachment]:
    found: dict[object, Attachment] = {}

    def add(filespec, source: str, tree_name: str | None = None, page: int | None = None):
        if not isinstance(filespec, pikepdf.Dictionary):
            return
        key = _key(filespec)
        att = found.get(key)
        if att is None:
            att = found[key] = _describe(filespec, tree_name)
            att.page = page
        if source not in att.sources:
            att.sources.append(source)

    root = pdf.Root
    names = root.get("/Names")
    if isinstance(names, pikepdf.Dictionary):
        for tree_name, filespec in _iter_name_tree(names.get("/EmbeddedFiles")):
            add(filespec, "names", tree_name)

    af = root.get("/AF")
    if isinstance(af, pikepdf.Array):
        for filespec in af:
            add(filespec, "catalog_af")

    for page_no, page in enumerate(pdf.pages, start=1):
        page_af = page.obj.get("/AF")
        if isinstance(page_af, pikepdf.Array):
            for filespec in page_af:
                add(filespec, "page_af", page=page_no)
        annots = page.obj.get("/Annots")
        if isinstance(annots, pikepdf.Array):
            for annot in annots:
                if isinstance(annot, pikepdf.Dictionary) and annot.get("/Subtype") == pikepdf.Name.FileAttachment:
                    add(annot.get("/FS"), "annotation", page=page_no)

    return list(found.values())


_UNSAFE = re.compile(r"[^\w.\- ()+]")


def safe_filename(name: str) -> str:
    """A file name that is safe to create in an output directory: no paths, no traversal."""
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", name).strip(" .")
    return name[:200] or "attachment"
