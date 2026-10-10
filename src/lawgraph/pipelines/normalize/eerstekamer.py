"""Normalize pipeline for the Kamerstukken of the Eerste Kamer.

A paper names its dossier (the number of the Tweede Kamer's kamerstukdossier, with its suffix
and title as the SRU record gives them: ``dossiernummer``, ``dossiertitel``). A dossier that no
node holds, because the Tweede Kamer's data has none (its OData begins about 2005; the papers
of 1995-2006 name thousands), is written from those papers: ``dossiers/<label>`` with its
number, suffix and the title its papers give most (of equal counts, that of the newest paper),
``source`` ``eerstekamer``, no kind or phases (those come from the papers of the Tweede Kamer
it does not have). A dossier the Tweede Kamer has is never written here; one it delivers
later takes this node over (``source`` ``tk``).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    MAX_TITLE_CHARS,
    RAW_KIND_EK_KAMERSTUK,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.display import shorten
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.dossier_stages import dossier_display_name
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records import dossier_label
from lawgraph.db import NodeWriter
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

_DOSSIER_RE = re.compile(r"^\s*(?P<number>\d+)(?:[\s-]+(?P<suffix>\S.*?))?\s*$")


def split_dossier_number(value: str | None) -> tuple[str | None, str | None]:
    """``"35925 VII"`` -> ``("35925", "VII")``; ``"36867"`` -> ``("36867", None)``.

    The Tweede Kamer stores the two parts as ``number`` and ``suffix`` of the dossier.
    """
    match = _DOSSIER_RE.match(value or "")
    if not match:
        return None, None
    return match["number"], match["suffix"]


def dossier_labels(payload: dict[str, Any]) -> list[str]:
    """The labels of every dossier a paper names (``36600-VII``), the first first; a value
    that is no dossier number (``CXIX``, a chapter of a budget written alone) is left out.
    A record retrieved before the client kept them all names only ``dossier_number``."""
    values = payload.get("dossier_numbers") or [payload.get("dossier_number")]
    labels: list[str] = []
    for value in values:
        number, suffix = split_dossier_number(value)
        label = dossier_label(number, suffix) if number else None
        if label and label not in labels:
            labels.append(label)
    return labels


def _dossier(key: str, papers: list[tuple[str, str, str | None, str]]) -> Node:
    """The dossier of *papers* (``(date, number, suffix, dossiertitel)``): its title the one
    its papers give most, of equal counts that of the newest paper."""
    _, number, suffix, _ = papers[0]
    titles = Counter(title for _, _, _, title in papers if title)
    newest = {title: date for date, _, _, title in sorted(papers) if title}
    title = max(titles, key=lambda t: (titles[t], newest[t])) if titles else None
    label = dossier_label(number, suffix)
    return Node(
        collection=COLLECTION_DOSSIERS,
        type=NodeType.DOSSIER,
        key=key,
        labels=["EK"],
        props={
            "number": number,
            "suffix": suffix or "",
            "label": label,
            "order": dossier_order(number, suffix),
            "title": title,
            "title_source": "eerstekamer" if title else None,
            "display_name": dossier_display_name(number, suffix, title or ""),
            "source": SOURCE_EERSTEKAMER,
        },
    )


class EerstekamerNormalizePipeline(NormalizePipelineBase):
    """Normalize the SRU records of Eerste Kamer Kamerstukken into documents."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EK_KAMERSTUK],
            since=since,
            batch_size=1000,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        count = 0
        writer = NodeWriter(self.store)
        dossiers: dict[str, list[tuple[str, str, str | None, str]]] = {}

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                result.skipped += 1
                continue
            identifier = payload.get("identifier") or record.get("external_id")
            if not identifier:
                result.skipped += 1
                continue
            node = self._paper(str(identifier), payload)
            writer.add(node)
            count += 1
            number = node.props.get("dossier_number")
            if number:
                label = dossier_label(number, node.props.get("dossier_suffix"))
                dossiers.setdefault(make_node_key(label), []).append(
                    (
                        str(node.props.get("date") or ""),
                        str(number),
                        node.props.get("dossier_suffix"),
                        str(node.props.get("subject") or ""),
                    )
                )

        writer.flush()
        made = self._write_dossiers(dossiers)
        logger.info(
            "Eerste Kamer normalize: %d Kamerstukken; %d dossiers no other source has, "
            "from their papers.",
            count,
            made,
        )
        return count

    def _write_dossiers(
        self, dossiers: dict[str, list[tuple[str, str, str | None, str]]]
    ) -> int:
        """Write each dossier of *dossiers* (key: its papers' ``(date, number, suffix,
        dossiertitel)``) that no node holds; how many."""
        if not dossiers:
            return 0
        known = self.store.existing_keys(COLLECTION_DOSSIERS, set(dossiers))
        nodes = [
            _dossier(key, papers)
            for key, papers in sorted(dossiers.items())
            if key not in known
        ]
        with NodeWriter(self.store) as writer:
            writer.add_all(nodes)
        return len(nodes)

    def _paper(self, identifier: str, payload: dict[str, Any]) -> Node:
        kind = payload.get("kind") or ""
        number = payload.get("number") or ""
        dossier_number, dossier_suffix = split_dossier_number(
            payload.get("dossier_number")
        )
        title = payload.get("document_title") or payload.get("title") or ""
        dossier = " ".join(part for part in (dossier_number, dossier_suffix) if part)
        # by letter, without "nr.": Kamerstukken I 36867, C
        paper = ", ".join(part for part in (f"Kamerstuk I {dossier}", number) if part)
        display_name = f"{paper}: {title}" if dossier else title

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": identifier,
            "kind": kind,
            "number": number,
            "title": title,
            "subject": payload.get("dossier_title") or "",
            "session_year": payload.get("session_year") or "",
            "display_name": shorten(display_name or identifier, MAX_TITLE_CHARS),
        }
        for name, value in (
            ("date", iso_date(payload.get("date"))),
            ("dossier_number", dossier_number),
            ("dossier_suffix", dossier_suffix),
            ("dossier_numbers", dossier_labels(payload)),
            ("url", payload.get("url")),
        ):
            if value:
                props[name] = value

        return Node(
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=make_node_key("ek", identifier),
            labels=["EersteKamer", "EK"],
            props=props,
        )

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """None. A paper reaches the graph through its dossier (of the Tweede Kamer, else the
        one written from its papers).

        ``EerstekamerSemanticPipeline`` matches the dossier number.
        """
