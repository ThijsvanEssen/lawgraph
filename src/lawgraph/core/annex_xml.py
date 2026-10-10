"""The annexes (``<bijlage>``) of a BWB toestand: their structure, key and node props.

``bwb_xml.parse_toestand`` reads them with the rest of the toestand, so ``normalize bwb``
writes the annex nodes from the one parse it already does.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS, SOURCE_BWB
from lawgraph.core.models import make_node_key
from lawgraph.core.xml import (
    collapse_ws,
    find_text,
    first_named,
    iter_named,
    local_name,
    text_of,
)

# The `source` of the annex edges, whoever writes them (it was one semantic pipeline).
ANNEX_EDGE_SOURCE = "bwb-annex-links"

MAX_ENTRIES = 200
MAX_DESCRIPTION_CHARS = 2000


def _collapsed(element: ET.Element) -> str:
    return collapse_ws(text_of(element))


def extract_kop(element: ET.Element) -> tuple[str | None, str | None]:
    """Return ``(label, title)`` from the annex's ``<kop>`` heading."""
    kop = first_named(element, "kop")
    if kop is None:
        return None, None
    label = find_text(kop, "nr", collapse=True, skip_empty=False)
    title = find_text(kop, "titel", collapse=True, skip_empty=False)
    return label, title


def _lead_in(element: ET.Element | None) -> str | None:
    """The paragraph that introduces a list ("Gemeentewet:"), without its colon; None when
    *element* is no paragraph ending in a colon."""
    if element is None or local_name(element.tag) != "al":
        return None
    text = _collapsed(element)
    if not text.endswith(":"):
        return None
    return text[:-1].strip() or None


def _own_text(li: ET.Element) -> str:
    """A list item without the lists inside it: its marker and its paragraphs (or its text
    when it has none)."""
    own = [collapse_ws(li.text)] + [
        _collapsed(child) for child in li if local_name(child.tag) in ("li.nr", "al")
    ]
    return " ".join(text for text in own if text)


def _add_list(
    lijst: ET.Element,
    entries: list[dict[str, Any]],
    heading: str | None,
    parent: int | None,
) -> None:
    """The items of *lijst* and of the lists inside them, each under its *parent* item."""
    for li in lijst:
        if local_name(li.tag) != "li" or len(entries) >= MAX_ENTRIES:
            continue
        index = parent
        text = _own_text(li)
        if text:
            index = len(entries)
            entries.append(
                {
                    "index": index,
                    "name": text,
                    "heading": heading,
                    "parent_index": parent,
                }
            )
        for nested in li:
            if local_name(nested.tag) == "lijst":
                _add_list(nested, entries, heading, index)


def _add_lists(element: ET.Element, entries: list[dict[str, Any]]) -> None:
    """The lists under *element* (also inside its articles and divisions), each under the
    paragraph that introduces it."""
    previous: ET.Element | None = None
    for child in element:
        name = local_name(child.tag)
        if name == "lijst":
            _add_list(child, entries, _lead_in(previous), None)
        elif name not in ("al", "kop", "meta-data"):
            _add_lists(child, entries)
        previous = child


def extract_entries(element: ET.Element) -> list[dict[str, Any]]:
    """The list items (``<li>``) of an annex as entries (capped), in document order.

    An entry is the item's own text (``a. artikel 49``), without the lists inside it: those
    are entries of their own, with ``parent_index`` the index of the item they are in.
    ``heading`` is the paragraph that introduces the outermost list ("Gemeentewet" of
    "Gemeentewet:"), for every entry in it; None when the list has no such paragraph.
    """
    entries: list[dict[str, Any]] = []
    _add_lists(element, entries)
    return entries


def extract_description(element: ET.Element) -> str | None:
    """Newline-joined paragraphs (``<al>``) outside list items, capped in length."""
    # Paragraphs inside list items belong to entries, not the description.
    in_li = {id(al) for li in iter_named(element, "li") for al in iter_named(li, "al")}
    parts: list[str] = []
    total = 0
    for node in iter_named(element, "al"):
        if id(node) in in_li:
            continue
        text = _collapsed(node)
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= MAX_DESCRIPTION_CHARS:
            break
    if not parts:
        return None
    return "\n".join(parts)[:MAX_DESCRIPTION_CHARS]


@dataclass(frozen=True)
class AnnexXml:
    label: str | None  # "I", "2"; None for the one annex of a regulation
    title: str | None
    description: str | None
    entries: tuple[dict[str, Any], ...]


def parse_annexes(root: ET.Element) -> tuple[AnnexXml, ...]:
    """The annexes of a toestand, the first of each label."""
    seen: set[str | None] = set()
    annexes = []
    for element in iter_named(root, "bijlage"):
        label, title = extract_kop(element)
        if label in seen:
            continue
        seen.add(label)
        annexes.append(
            AnnexXml(
                label,
                title,
                extract_description(element),
                tuple(extract_entries(element)),
            )
        )
    return tuple(annexes)


def annex_node_key(bwb_id: str, label: str | None) -> str:
    """Deterministic annex key: ``<bwb_id>_annex[_<label>]``."""
    return make_node_key(bwb_id, "annex", label)


def annex_props(
    annex: AnnexXml, bwb_id: str, citation_title: str | None = None
) -> dict[str, Any]:
    """Props of the Annex node; *citation_title* that of its law, which its title cites."""
    display = annex.title or (f"Annex {annex.label}" if annex.label else "Annex")
    return {
        "source": SOURCE_BWB,
        "bwb_id": bwb_id,
        "label": annex.label,
        "title": annex.title,
        "display_name": display,
        "description": annex.description,
        "entries": list(annex.entries) or None,
        "instrument_id": f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}",
        "instrument_citation_title": citation_title,
    }
