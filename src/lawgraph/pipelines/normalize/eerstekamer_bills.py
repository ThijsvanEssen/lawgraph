"""Normalize the pages of the bills of the Eerste Kamer onto their dossiers.

Every bill page (``ek-bill-html``) the graph holds the dossier of gets ``ek_bill`` on that
dossier, as the page gives it (``core.ek_bills``): the day it was submitted
(``Kerngegevens``: ``ingediend``), its progress block by block (phase, house, state as the
page marks it, and its documents with kind, date and number), the heading of the list of its
committee it was found under, and the page it was taken over from with the day it was read.
A bill whose dossier the graph does not hold is skipped.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    RAW_KIND_EERSTEKAMER_BILL,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_bills
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.official_urls import ek_url
from lawgraph.db import NodeWriter
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


def ek_bill(bill: ek_bills.Bill, meta: dict[str, Any]) -> dict[str, Any]:
    """The ``ek_bill`` prop of a dossier from its page and the meta of its record."""
    return {
        "url": meta.get("url"),
        "read_on": meta.get("read_on"),
        "status": meta.get("status"),
        "submitted_on": bill.submitted_on,
        "progress": [
            {
                **{k: v for k, v in asdict(step).items() if k != "papers"},
                "papers": [
                    {**asdict(document), "url": ek_url(document.url)}
                    for document in step.papers
                ],
            }
            for step in bill.progress
        ],
    }


class EerstekamerBillsNormalizePipeline(NormalizePipelineBase[Records]):
    """``ek_bill`` on the dossier of every bill page of the Eerste Kamer."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EERSTEKAMER_BILL],
            since=since,
            batch_size=50,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """``ek_bill`` on the dossiers. No edges: a bill page adds to its dossier only."""
        found: dict[str, dict[str, Any]] = {}
        for record in raw:
            bill = ek_bills.bill(self._payload_text(record) or "")
            if not bill.label:
                self.progress.skip("no dossier on the page", record.get("external_id"))
                continue
            found[make_node_key(bill.label)] = ek_bill(bill, self._meta(record))
        known = self.store.existing_keys(COLLECTION_DOSSIERS, set(found))
        for key in sorted(set(found) - known):
            self.progress.skip("dossier not in the graph", key)
        nodes = [
            Node(
                collection=COLLECTION_DOSSIERS,
                key=key,
                labels=[],
                props={"ek_bill": found[key]},
            )
            for key in sorted(known)
        ]
        with NodeWriter(self.store) as writer:
            writer.add_all(nodes)
        logger.info(
            "Eerste Kamer: %d bill pages, %d on a dossier the graph holds.",
            len(found),
            len(nodes),
        )
