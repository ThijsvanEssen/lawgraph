"""Pure helpers for KOOP publication XML (Staatsblad, Staatscourant)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.xml import find_text, local_name

# Both spellings occur in the published XML for the official title.
OFFICIAL_TITLE_TAGS = ("officiele-titel", "officieletitel")


def publication_title(root: ET.Element, fallback: str) -> str:
    """Best title of a publication: citation title, official title, title, *fallback*."""
    return (
        find_text(root, "citeertitel")
        or find_text(root, *OFFICIAL_TITLE_TAGS)
        or find_text(root, "titel")
        or fallback
    )


def staatsblad_ref_from_bwb_xml(bwb_xml: str) -> tuple[str, str] | None:
    """Find the Staatsblad ``(year, number)`` a BWB toestand XML refers to.

    Looks for ``publicatiejaar`` / ``publicatienummer`` elements first, then for
    an ``stb-<year>-<number>`` reference in any attribute, then anywhere in the
    raw text. Returns ``None`` when nothing is found or the XML is malformed.
    """
    try:
        root = ET.fromstring(bwb_xml)
    except ET.ParseError:
        return None

    year: str | None = None
    number: str | None = None
    for element in root.iter():
        name = local_name(element.tag)
        value = (element.text or "").strip()
        if name == "publicatiejaar" and value.isdigit():
            year = value
        if name == "publicatienummer" and value:
            number = value

    if not (year and number):
        for element in root.iter():
            for attribute in element.attrib.values():
                match = STB_ID_PATTERN.search(attribute)
                if match:
                    return match.group(1), match.group(2)
    if year and number:
        return year, number

    match = STB_ID_PATTERN.search(bwb_xml)
    return (match.group(1), match.group(2)) if match else None
