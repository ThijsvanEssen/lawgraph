"""Normalize pipeline for the Kamerstukken of the Eerste Kamer.

A document names its dossier (the number of the Tweede Kamer's kamerstukdossier, with its suffix
and title as the SRU record gives them: ``dossiernummer``, ``dossiertitel``). A dossier that no
node holds (the documents of 1995-2006 name thousands) is written from those documents, with
``source`` ``eerstekamer`` (``_paper_dossiers``).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_DOCUMENTS,
    LABEL_EERSTE_KAMER,
    MAX_TITLE_CHARS,
    RAW_KIND_EERSTEKAMER_KAMERSTUK,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.display import shorten
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records.dossiers import dossier_label
from lawgraph.db import NodeWriter
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.pipelines.normalize._paper_dossiers import (
    Papers,
    add_paper,
    write_unknown_dossiers,
)
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

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
    """The labels of every dossier a document names (``36600-VII``), the first first; a value
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


def unique_documents(nodes: Iterable[Node]) -> list[Node]:
    """*nodes* with one document for each Kamerstuk. The SRU index holds a Kamerstuk twice when it
    has two identifiers (``kst-36702-A`` and ``kst-1274193``); the Kamerstuk is told by its dossier
    (number and suffix), its letter and its date. Of the copies the one with the identifier
    ``kst-<dossier>-<letter>`` stays, else the first by key. A document without a dossier or
    letter is never taken for a copy."""
    kept: dict[tuple[str, ...], Node] = {}
    loose: list[Node] = []
    for node in nodes:
        props = node.props
        same = tuple(
            str(props.get(name) or "")
            for name in ("dossier_number", "dossier_suffix", "number", "date")
        )
        if not (same[0] and same[2] and same[3]):
            loose.append(node)
            continue
        current = kept.get(same)
        if current is None or _document_rank(node) < _document_rank(current):
            kept[same] = node
    return [*kept.values(), *loose]


def _document_rank(node: Node) -> tuple[bool, str | None]:
    return (
        not str(node.props.get("external_id")).startswith(
            "kst-" + str(node.props.get("dossier_number")) + "-"
        ),
        node.key,
    )


class EerstekamerNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalize the SRU records of Eerste Kamer Kamerstukken into documents."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EERSTEKAMER_KAMERSTUK],
            since=since,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The documents, and the dossiers of their own. No edges: a document reaches the
        graph through its dossier (of the Tweede Kamer, else the one written from its
        documents); ``EerstekamerSemanticPipeline`` matches the dossier number."""
        count = 0
        writer = NodeWriter(self.store)
        dossiers: dict[str, Papers] = {}

        for node in self._unique_documents(raw):
            writer.add(node)
            count += 1
            add_paper(dossiers, node)

        writer.flush()
        made = write_unknown_dossiers(
            self.store, dossiers, CHAMBER_EK, SOURCE_EERSTEKAMER
        )
        logger.info(
            "Eerste Kamer normalize: %d Kamerstukken; %d dossiers no other source has, "
            "from their papers.",
            count,
            made,
        )

    def _unique_documents(self, raw: Records) -> list[Node]:
        """The documents of *raw* to write: one for each Kamerstuk, also of the ones written
        before. A run with ``--since`` may see one copy where an earlier run wrote the other
        (``kst-1274193``, later ``kst-36702-A``): the copy that loses goes, with its edges,
        and one that loses to a document written before is not written."""
        nodes = list(self._documents(raw))
        own = {node.key for node in nodes}
        numbers = sorted(
            {
                str(n.props["dossier_number"])
                for n in nodes
                if n.props.get("dossier_number")
            }
        )
        written = [
            Node.skeleton(COLLECTION_DOCUMENTS, row["key"], row["props"])
            for row in normalize_ek.ek_documents_of_dossiers(self.store, numbers)
            if row["key"] not in own
        ]
        kept = unique_documents([*nodes, *written])
        kept_keys = {node.key for node in kept}
        gone = [str(node.key) for node in written if node.key not in kept_keys]
        if gone:
            removed = removals.remove_nodes(self.store, COLLECTION_DOCUMENTS, gone)
            logger.info(
                "Eerste Kamer normalize: %d copies of a Kamerstuk removed.", removed
            )
        return [node for node in kept if node.key in own]

    def _documents(self, raw: Records) -> Iterator[Node]:
        for record in raw:
            payload = payload_json(record)
            if not payload:
                self.progress.skip("no payload", record.get("external_id"))
                continue
            identifier = payload.get("identifier") or record.get("external_id")
            if not identifier:
                self.progress.skip("no identifier", record.get("key"))
                continue
            yield self._document(str(identifier), payload)

    def _document(self, identifier: str, payload: dict[str, Any]) -> Node:
        kind = payload.get("kind") or ""
        number = payload.get("number") or ""
        dossier_number, dossier_suffix = split_dossier_number(
            payload.get("dossier_number")
        )
        title = payload.get("document_title") or payload.get("title") or ""
        dossier = " ".join(part for part in (dossier_number, dossier_suffix) if part)
        # by letter, without "nr.": Kamerstukken I 36867, C
        document = ", ".join(
            part for part in (f"Kamerstuk I {dossier}", number) if part
        )
        display_name = f"{document}: {title}" if dossier else title

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
            key=make_node_key("ek", identifier),
            labels=[LABEL_EERSTE_KAMER, CHAMBER_EK],
            props=props,
        )
