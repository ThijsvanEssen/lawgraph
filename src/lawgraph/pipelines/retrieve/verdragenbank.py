"""Retrieve pipeline for Dutch Verdragenbank (treaty register).

Two kinds of record per treaty: its SRU record (``verdrag-json``: title, dates, type,
status) and its item XML (``verdrag-xml``: parties, Tractatenbladen, dossiers, related
treaties; ``core.verdragenbank_xml``). The item XML of a treaty is fetched when it is not
stored yet or the register changed it since (its ``modified``); a 404 is remembered as a
missing record, so it is not asked for again at once. ``only_stored`` keeps a run to the
treaties whose SRU record is stored already (a small database: no new treaties).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.clients.verdragenbank import VerdragenbankClient
from lawgraph.config.constants import (
    RAW_KIND_VERDRAG,
    RAW_KIND_VERDRAG_XML,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)


class VerdragenbankRetrievePipeline(RetrievePipelineBase):
    """Retrieve the treaties of the Verdragenbank: their SRU records and item XML."""

    def __init__(
        self, store: GraphStore, client: VerdragenbankClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or VerdragenbankClient()

    def fetch(
        self,
        *,
        max_records: int | None = None,
        only_stored: bool = False,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        stored = (
            set(self._stored_at(SOURCE_VERDRAGENBANK, RAW_KIND_VERDRAG))
            if only_stored
            else None
        )
        treaties = self.client.enumerate_treaties(max_records=max_records)
        listed: list[dict[str, Any]] = []
        for treaty in treaties:
            uri = treaty.get("uri") or ""
            if not uri:
                continue
            # Use the last path segment as the external ID
            external_id = uri.rstrip("/").rsplit("/", 1)[-1] or uri
            if stored is not None and external_id not in stored:
                continue
            listed.append({**treaty, "identifier": external_id})
            yield RetrieveRecord(
                source=SOURCE_VERDRAGENBANK,
                kind=RAW_KIND_VERDRAG,
                external_id=external_id,
                payload_json={k: v for k, v in treaty.items() if k != "modified"},
                meta={
                    "verdragsnummer": treaty.get("verdragsnummer"),
                    "status": treaty.get("status"),
                },
            )
        logger.info("Verdragenbank retrieve: %d treaty records.", len(listed))
        yield from self._items(listed)

    def _items(self, listed: list[dict[str, Any]]) -> Iterator[RetrieveRecord]:
        """The item XML of every treaty in *listed* that is new or changed."""
        changed = set(
            self._without_missing(
                SOURCE_VERDRAGENBANK,
                RAW_KIND_VERDRAG_XML,
                self._changed(SOURCE_VERDRAGENBANK, RAW_KIND_VERDRAG_XML, listed),
            )
        )
        todo = [t for t in listed if t["identifier"] in changed and t.get("item_url")]
        logger.info(
            "Verdragenbank retrieve: the item XML of %d of %d treaties is new or changed.",
            len(todo),
            len(listed),
        )
        by_id = {treaty["identifier"]: treaty for treaty in todo}
        yield from self._download_each(
            list(by_id),
            lambda identifier: self.client.fetch_treaty_xml(
                by_id[identifier]["item_url"]
            ),
            lambda identifier, xml: [
                RetrieveRecord(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAG_XML,
                    external_id=identifier,
                    payload_text=xml,
                    meta={
                        "item_url": by_id[identifier]["item_url"],
                        "modified": by_id[identifier].get("modified"),
                    },
                )
            ],
            source="Verdragenbank item XML",
            missing=lambda identifier, status: missing_record(
                SOURCE_VERDRAGENBANK,
                RAW_KIND_VERDRAG_XML,
                identifier,
                listed=True,
                status=status,
            ),
        )
