"""XML parsing hardened for untrusted input: no entity expansion, no DTD loading, no network."""

from __future__ import annotations

from lxml import etree


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                           dtd_validation=False, huge_tree=False, remove_comments=False)


def parse_xml(data: bytes) -> etree._Element:
    return etree.fromstring(data, parser=_parser())
