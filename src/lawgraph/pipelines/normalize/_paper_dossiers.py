"""The dossiers the Kamerstukken of the SRU name and no other source has.

A Kamerstuk of the SRU names its dossier (the number of the Tweede Kamer's kamerstukdossier,
with its suffix and title: ``dossiernummer``, ``dossiertitel``). A dossier that no node holds,
because the Tweede Kamer's own data has none (its OData begins about 2005), is written from
those papers: ``dossiers/<label>`` with its number, suffix and the title its papers give most
(of equal counts, that of the newest paper), no kind or phases (those come from the Tweede
Kamer's data it does not have). A dossier the Tweede Kamer has is never written here; one it
delivers later takes this node over (``source`` ``tk``).
"""

from __future__ import annotations

from collections import Counter

from lawgraph.config.constants import COLLECTION_DOSSIERS, Chamber
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.models import Node, make_node_key
from lawgraph.core.tk_records.dossiers import dossier_display_name, dossier_label
from lawgraph.db import NodeWriter
from lawgraph.db.counting import Store

# The papers of a dossier: ``(date, number, suffix, dossiertitel)`` of each.
Papers = list[tuple[str, str, str | None, str]]


def add_paper(dossiers: dict[str, Papers], node: Node) -> None:
    """Note the document *node* under the key of its dossier, if it names one."""
    number = node.props.get("dossier_number")
    if not number:
        return
    suffix = node.props.get("dossier_suffix")
    dossiers.setdefault(make_node_key(dossier_label(number, suffix)), []).append(
        (
            str(node.props.get("date") or ""),
            str(number),
            suffix,
            str(node.props.get("subject") or ""),
        )
    )


def dossier_of_papers(key: str, papers: Papers, chamber: Chamber, source: str) -> Node:
    """The dossier of *papers*: its title the one they give most, of equal counts that of
    the newest paper."""
    _, number, suffix, _ = papers[0]
    titles = Counter(title for _, _, _, title in papers if title)
    newest = {title: date for date, _, _, title in sorted(papers) if title}
    title = max(titles, key=lambda t: (titles[t], newest[t])) if titles else None
    label = dossier_label(number, suffix)
    return Node(
        collection=COLLECTION_DOSSIERS,
        key=key,
        labels=[chamber],
        props={
            "number": number,
            "suffix": suffix or "",
            "label": label,
            "order": dossier_order(number, suffix),
            "title": title,
            "title_source": source if title else None,
            "display_name": dossier_display_name(number, suffix, title or ""),
            "source": source,
        },
    )


def write_unknown_dossiers(
    store: Store, dossiers: dict[str, Papers], chamber: Chamber, source: str
) -> int:
    """Write each dossier of *dossiers* that no node holds; how many."""
    if not dossiers:
        return 0
    known = store.existing_keys(COLLECTION_DOSSIERS, set(dossiers))
    nodes = [
        dossier_of_papers(key, papers, chamber, source)
        for key, papers in sorted(dossiers.items())
        if key not in known
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
    return len(nodes)
