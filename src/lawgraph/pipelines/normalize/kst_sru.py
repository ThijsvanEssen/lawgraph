"""Normalize pipeline for the Kamerstukken of the Tweede Kamer of 1994-1995 to 2007-2008 (KOOP SRU).

Each SRU record becomes a document of the Tweede Kamer (label ``TK``, ``source`` ``kst``, key
``kst_25877_3`` of ``kst-25877-3``), numbered in its dossier as a document of the Tweede
Kamer's API is (``dossier_number``, ``dossier_suffix``, ``sequence``), so ``retrieve
tk-content`` fetches its XML and ``normalize tk-content`` reads it. Its kind and own title are
read from the SRU title (``core.kst_documents``). A paper whose address is not its identifier,
or whose number is not a number (``kst-20012002-25877-58b``, a letter ``kst-25877-A``), has
no ``sequence``: its XML is not asked for. A reprint (``kst-17050-309-h1``, often in a later
session year) is the paper: its node is that of the paper (``kst_17050_309``), whichever comes
last.

A paper the Tweede Kamer's API holds too (in 2007-2008 a third) is its document: the copy of
the SRU goes, with its edges. The dossiers no other source has are written from the documents
(``_document_dossiers``, ``source`` ``kst``); ``semantic kst-sru`` links each paper to its dossier.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_DOCUMENTS,
    MAX_TITLE_CHARS,
    RAW_KIND_KST_SRU,
    SOURCE_KST,
)
from lawgraph.core.display import shorten
from lawgraph.core.document_completeness import kamerstuk_address
from lawgraph.core.kst_documents import kind_and_title
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.core.time import iso_date
from lawgraph.core.tk_records.documents import document_display_name
from lawgraph.core.tk_records.dossiers import dossier_label
from lawgraph.db import NodeWriter
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import kst_sru as normalize_kst
from lawgraph.pipelines.normalize._document_dossiers import (
    DossierDocuments,
    add_document,
    write_unknown_dossiers,
)
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records
from lawgraph.pipelines.normalize.eerstekamer import (
    dossier_labels,
    split_dossier_number,
)

logger = get_logger(__name__)

_REPRINT_RE = re.compile(r"-h\d+$")


def kst_document(identifier: str, payload: dict[str, Any]) -> Node:
    """The document of the SRU record *payload* of the paper *identifier*."""
    base_id = _REPRINT_RE.sub("", identifier)
    number, suffix = split_dossier_number(payload.get("dossier_number"))
    numbers = payload.get("numbers") or []
    # "1;2": a bill with its royal message; "199;7f": the paper is also nr. 7f of another
    first = re.split(r"[;,\s]+", str(numbers[0]))[0] if numbers else ""
    address = kamerstuk_address(number, suffix, first)
    sequence = None
    if first.isdigit() and address and address.lower() == base_id.lower():
        sequence = int(first)
    kind, title = kind_and_title(payload.get("title") or "")
    label = dossier_label(number, suffix) if number else None

    props: dict[str, Any] = {
        "source": SOURCE_KST,
        "external_id": identifier,
        "kind": kind,
        "title": title,
        "subject": payload.get("dossier_title") or "",
        "session_year": payload.get("session_year") or "",
        "display_name": shorten(
            document_display_name(label, sequence, kind, title) or identifier,
            MAX_TITLE_CHARS,
        ),
    }
    for name, value in (
        ("date", iso_date(payload.get("date"))),
        ("dossier_number", number),
        ("dossier_suffix", suffix),
        ("dossier_numbers", dossier_labels(payload)),
        ("sequence", sequence),
        ("url", payload.get("url")),
        ("pdf_url", payload.get("pdf_url")),
    ):
        if value:
            props[name] = value

    return Node(
        collection=COLLECTION_DOCUMENTS,
        key=make_node_key(base_id),
        labels=[CHAMBER_TK],
        props=props,
    )


class KstSruNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalize the SRU records of Tweede Kamer Kamerstukken into documents."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_KST, kinds=[RAW_KIND_KST_SRU], since=since
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The documents, the dossiers of their own, and no copy of a paper of the API."""
        count = 0
        dossiers: dict[str, DossierDocuments] = {}
        with NodeWriter(self.store) as writer:
            for node in self._documents(raw):
                writer.add(node)
                count += 1
                add_document(dossiers, node)
        made = write_unknown_dossiers(self.store, dossiers, CHAMBER_TK, SOURCE_KST)
        copies = normalize_kst.kst_copies_of_tk_documents(self.store)
        removed = removals.remove_nodes(self.store, COLLECTION_DOCUMENTS, copies)
        logger.info(
            "Tweede Kamer papers of the SRU: %d; %d dossiers no other source has; %d "
            "copies of a paper of the Tweede Kamer's API removed.",
            count,
            made,
            removed,
        )

    def _documents(self, raw: Records) -> Iterator[Node]:
        for record in raw:
            payload = payload_json(record)
            identifier = (payload or {}).get("identifier") or record.get("external_id")
            if not payload or not identifier:
                self.progress.skip("no payload", record.get("key"))
                continue
            yield kst_document(str(identifier), payload)
