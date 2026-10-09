"""``semantic bwb-definitions``: the definitions each regulation gives itself.

Reads the stored toestand XML of each regulation (``retrieve bwb``: no new fetch) and keeps
its begripsbepalingen (``core.bwb_definitions``) in ``lg_instrument_definitions``, apart from
the instrument's props. The article routes mark the terms with them, the instrument routes
list them. A regulation read is kept in full: one without definitions loses its row.

``--since``: the toestanden fetched since then (the daily run). Without it every one; a full
run is long (every toestand read), so it goes in slices: ``--after BWB-ID`` starts past
that regulation, ``--limit N`` stops after N, and the log names the last one read.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.bwb_definitions import definitions
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import definitions as definitions_queries
from lawgraph.db.store import GraphStore

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Regulations written at a time.
_BATCH = 200


class BWBDefinitionsSemanticPipeline(SemanticPipelineBase):
    """The definitions of each regulation, into ``lg_instrument_definitions``."""

    def __init__(
        self, *, store: GraphStore, after: str | None = None, limit: int | None = None
    ) -> None:
        super().__init__(store=store)
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        refs = definitions_queries.toestanden(
            self.store,
            since_iso=iso_timestamp(since),
            after=self.after,
            limit=self.limit,
        )
        found: dict[str, list[dict[str, Any]]] = {}
        last = None
        with_any = total = 0
        for row in self._track(self.store.with_payloads(refs), "toestanden"):
            last = row["bwb_id"]
            xml = row.get("payload_text")
            if not xml:
                result.skipped += 1
                continue
            try:
                found[last] = definitions(last, xml)
            except ET.ParseError as exc:
                logger.warning("The toestand of %s cannot be read: %s", last, exc)
                result.skipped += 1
                continue
            with_any += bool(found[last])
            total += len(found[last])
            if len(found) >= _BATCH:
                definitions_queries.keep_definitions(self.store, found)
                result.updated += len(found)
                found = {}
        definitions_queries.keep_definitions(self.store, found)
        result.updated += len(found)
        logger.info(
            "Definitions: %d of the regulations read give any, %d in all; the last read "
            "was %s (go on with --after %s).",
            with_any,
            total,
            last,
            last,
        )
        return result
