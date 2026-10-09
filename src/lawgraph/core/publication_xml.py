"""Pure helpers for KOOP publication XML (Staatsblad, Staatscourant)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.xml import find_text, iter_named, local_name, text_of

# Both spellings occur in the published XML for the official title.
OFFICIAL_TITLE_TAGS = ("officiele-titel", "officieletitel")


# The names of the series, which the first ``<titel>`` of a publication holds as its
# masthead ("Staatsblad van het Koninkrijk der Nederlanden"): no title of its own.
SERIES_NAMES = frozenset({"staatsblad", "staatscourant", "tractatenblad"})


def is_series_name(title: str | None) -> bool:
    """Whether *title* is only the name of a series (``Staatsblad``)."""
    return (title or "").strip().lower() in SERIES_NAMES


def _meta_title(root: ET.Element) -> str | None:
    """The ``DC.title`` of the metadata: the title of the publication itself."""
    for meta in iter_named(root, "meta"):
        if meta.get("name") == "DC.title" and (meta.get("content") or "").strip():
            return " ".join((meta.get("content") or "").split())
    return None


def _first_title(root: ET.Element) -> str | None:
    """The first ``<titel>`` that is not the masthead of the series."""
    for node in iter_named(root, "titel"):
        text = " ".join(text_of(node).split())
        if text and not is_series_name(text):
            return text
    return None


def publication_title(root: ET.Element, fallback: str) -> str:
    """Best title of a publication: citation title, official title, the ``DC.title`` of its
    metadata, its first title that is not the name of the series, *fallback*."""
    return (
        find_text(root, "citeertitel")
        or find_text(root, *OFFICIAL_TITLE_TAGS)
        or _meta_title(root)
        or _first_title(root)
        or fallback
    )


# The number of a publication, as BWB writes it (``publicatienr``) and as the KOOP XML does.
_NUMBER_TAGS = ("publicatienr", "publicatienummer")


def staatsblad_ref_from_bwb_xml(bwb_xml: str) -> tuple[str, str] | None:
    """Find the Staatsblad ``(year, number)`` a BWB toestand XML refers to.

    The ``<publicatie soort="Stb">`` of its brondata, the one that made the regulation
    (``effect="nieuwe-regeling"``) before any other; else a year and a number outside one;
    else an ``stb-<year>-<number>`` reference in any attribute, then anywhere in the raw
    text. Returns ``None`` when nothing
    is found or the XML is malformed.
    """
    try:
        root = ET.fromstring(bwb_xml)
    except ET.ParseError:
        return None

    published = [
        (element, ref)
        for element in root.iter()
        if local_name(element.tag) == "publicatie"
        and (element.get("soort") or "").lower() == "stb"
        and (ref := _year_and_number(element))
    ]
    if published:
        made = [r for e, r in published if e.get("effect") == "nieuwe-regeling"]
        return (made or [r for _, r in published])[0]

    # a year and a number outside a <publicatie>, as the KOOP XML writes them
    loose = _year_and_number(root) or next(
        (ref for element in root.iter() if (ref := _year_and_number(element))), None
    )
    if loose:
        return loose

    for element in root.iter():
        for attribute in element.attrib.values():
            match = STB_ID_PATTERN.search(attribute)
            if match:
                return match.group(1), match.group(2)
    match = STB_ID_PATTERN.search(bwb_xml)
    return (match.group(1), match.group(2)) if match else None


def _year_and_number(publication: ET.Element) -> tuple[str, str] | None:
    """``(year, number)`` of a ``<publicatie>``, from its children; None without both."""
    year = number = ""
    for child in publication:
        name = local_name(child.tag)
        value = (child.text or "").strip()
        if name == "publicatiejaar" and value.isdigit():
            year = value
        elif name in _NUMBER_TAGS and value:
            number = value
    return (year, number) if year and number else None
