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
from lawgraph.core.xml import collapse_ws, find_text, first_named, iter_named, text_of

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


def extract_entries(element: ET.Element) -> list[dict[str, Any]]:
    """Collect list items (``<li>``) as structured annex entries (capped)."""
    entries: list[dict[str, Any]] = []
    for node in iter_named(element, "li"):
        text = _collapsed(node)
        if not text:
            continue
        entries.append({"index": len(entries), "name": text})
        if len(entries) >= MAX_ENTRIES:
            break
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


def annex_props(annex: AnnexXml, bwb_id: str) -> dict[str, Any]:
    """Props of the Annex node."""
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
    }
