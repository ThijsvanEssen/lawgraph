"""Normalize the pages of the commitments of the Eerste Kamer (``retrieve
eerstekamer-commitments``) into commitments, beside those of the Tweede Kamer.

The page (``core.ek_commitments``) gives a commitment its number (``T04275``), its text, its
status (as the Kamer writes it, with a capital: ``Openstaand``, ``Voldaan``, ``Deels
voldaan``, ``Afgevoerd``), the day it was made (``made_on``) and its deadline
(``expected_resolution``), the offices responsible (``responsible``; the first is
``minister_role``), and the name of who spoke for the government in an office of that kind in
the passage quoted (``minister_name``: ``Vijlbrief``). Who that is, and the post, ministry and
cabinet, are derived by ``semantic eerstekamer-government``. A commitment is ``ABOUT`` each
stored dossier of its Kamerstukken (``meta.basis`` ``kamerstukken``), derived in full: a
dossier the page no longer names goes. A page without a number is skipped.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOSSIERS,
    LABEL_EERSTE_KAMER,
    RAW_KIND_EERSTEKAMER_COMMITMENT,
    RELATION_ABOUT,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_commitments
from lawgraph.core.display import shorten
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.official_urls import ek_url
from lawgraph.core.provenance import BASIS_DOCUMENTS
from lawgraph.core.raw_records import payload_text
from lawgraph.db import NodeWriter
from lawgraph.db.edges import EdgeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records
from lawgraph.sources.addresses import edge_source

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)


def commitment_key(number: str) -> str:
    """The key of the commitment of the Eerste Kamer numbered *number* (``ek_T04275``)."""
    return make_node_key("ek", number)


def commitment_node(
    path: str, page: ek_commitments.CommitmentPage, meta: dict[str, Any]
) -> Node:
    """The commitment a page of the Eerste Kamer is of."""
    status = page.status or ""
    return Node(
        collection=COLLECTION_COMMITMENTS,
        key=commitment_key(page.number),
        labels=[LABEL_EERSTE_KAMER, CHAMBER_EK],
        props={
            "source": SOURCE_EERSTEKAMER,
            "external_id": path,
            "number": page.number,
            "text": page.text,
            "display_name": shorten(page.text, 80) if page.text else None,
            "status": status[:1].upper() + status[1:] or None,
            "made_on": page.made_on,
            "expected_resolution": page.deadline,
            "minister_role": page.responsible[0] if page.responsible else None,
            "minister_name": ek_commitments.maker(page),
            "responsible": page.responsible,
            "responsible_now": page.responsible_now or None,
            "former_number": page.former_number,
            "asked_by": page.members,
            "committees": page.committees,
            "activity_kind": page.activity_kind,
            "category": page.category,
            "subjects": page.subjects,
            "documents": page.documents,
            "dossier_labels": page.dossiers,
            "citation": page.citation,
            "url": meta.get("url") or ek_url(path),
            "read_on": meta.get("read_on"),
        },
    )


class EerstekamerCommitmentsNormalizePipeline(NormalizePipelineBase[Records]):
    """The commitments of the Eerste Kamer, and the dossiers they are about."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EERSTEKAMER_COMMITMENT],
            since=since,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The commitments, then the dossiers they are about."""
        self._link(self._write_nodes(raw))

    def _write_nodes(self, raw: Records) -> dict[str, list[str]]:
        """Write the commitments; ``{id: dossier labels}`` of those written."""
        written: dict[str, list[str]] = {}
        with NodeWriter(self.store) as writer:
            for record in raw:
                path = str(record["external_id"])
                page = ek_commitments.commitment_page(payload_text(record) or "")
                if page is None:
                    self.progress.skip("no commitment on the page", path)
                    continue
                node = commitment_node(path, page, record.get("meta") or {})
                writer.add(node)
                written[
                    node_id(COLLECTION_COMMITMENTS, commitment_key(page.number))
                ] = page.dossiers
        logger.info("Eerste Kamer commitments: %d written.", len(written))
        return written

    def _link(self, written: dict[str, list[str]]) -> None:
        """``ABOUT`` from each commitment to the stored dossiers of its Kamerstukken."""
        stored = self.store.existing_keys(
            COLLECTION_DOSSIERS,
            {make_node_key(label) for labels in written.values() for label in labels},
        )
        writer = EdgeWriter(
            self.store, what="ABOUT edges of commitments", remembers=True
        )
        for commitment, labels in written.items():
            for label in labels:
                key = make_node_key(label)
                if key not in stored:
                    self.progress.note("dossier not in the graph", label)
                    continue
                writer.add(
                    commitment,
                    node_id(COLLECTION_DOSSIERS, key),
                    RELATION_ABOUT,
                    source=EDGE_SOURCE,
                    meta={"basis": BASIS_DOCUMENTS},
                )
        writer.flush()
        writer.remove_stale(
            RELATION_ABOUT,
            EDGE_SOURCE,
            list(written),
            to_collections=[COLLECTION_DOSSIERS],
        )
