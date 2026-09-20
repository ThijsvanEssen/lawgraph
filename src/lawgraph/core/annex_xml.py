"""Pure extraction of annex structure from BWB ``<bijlage>`` XML elements."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.xml import collapse_ws, find_text, first_named, iter_named, text_of

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
