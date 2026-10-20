"""``semantic bwb-definitions``: the definitions each regulation gives itself.

Reads the stored toestand XML of each regulation (``retrieve bwb``: no new fetch) and keeps
its begripsbepalingen (``core.bwb_definitions``) in ``lg_instrument_definitions``, apart from
the instrument's props. The article routes mark the terms with them, the instrument routes
list them. A regulation read is kept in full: one without definitions loses its row.

The laws of the Staatsblad the BWB does not hold (yet) are read the same way, from the
publications ``retrieve staatsblad`` stored (``core.staatsblad_laws.law_definitions``: the
text ``normalize staatsblad-laws`` reads, the divisions later laws replaced in place), each
under its official id; each law keeps how many it gives (``definitions_found``: what
``enrichment.definitions`` of the API says). A run that reaches the end of the toestanden
reads them: their ids (``stb-2026-56``) sort after every BWB id.

``--since``: the toestanden fetched since then (the daily run). Without it every one; a full
run is long (every toestand read), so it goes in slices: ``--after BWB-ID`` starts past
that regulation, ``--limit N`` stops after N, and the log names the last one read. A run
without ``--since`` reads every stored toestand of its range, so a regulation of that range
whose toestand is no longer stored loses its row, as a build would have none.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.bwb_definitions import definitions
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, node_id
from lawgraph.core.publications import law_key
from lawgraph.core.staatsblad_laws import law_definitions, law_text, read_records
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import definitions as definitions_queries
from lawgraph.db.queries import staatsblad_laws as law_queries
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
        seen: list[str] = []
        with_any = total = 0
        for row in self._track(self.store.with_payloads(refs), "toestanden"):
            last = row["bwb_id"]
            seen.append(last)
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
        # a slice that stopped at its limit reaches its last regulation, else the end
        upto = last if self.limit and len(seen) >= self.limit else None
        if upto is None:
            laws = self._staatsblad_laws()
            definitions_queries.keep_definitions(
                self.store, laws, instrument_key=law_key
            )
            seen += sorted(laws)
            result.updated += len(laws)
        if since is None:
            gone = definitions_queries.remove_definitions_except(
                self.store, seen, after=self.after, upto=upto
            )
            if gone:
                logger.info("Definitions: %d regulations no longer stored.", gone)
            result.updated += gone
        logger.info(
            "Definitions: %d of the regulations read give any, %d in all; the last read "
            "was %s (go on with --after %s).",
            with_any,
            total,
            last,
            last,
        )
        return result

    def _staatsblad_laws(self) -> dict[str, list[dict[str, Any]]]:
        """The definitions of each law of the Staatsblad the graph holds (official id ->
        its definitions); each law keeps how many."""
        publications, _ = read_records(law_queries.law_records(self.store))
        laws = {row["official_id"]: row for row in law_queries.laws(self.store)}
        found = {
            law.official_id: law_definitions(law, law_text(law, publications))
            for law in publications
            if law.official_id in laws
        }
        law_queries.keep_counts(
            self.store,
            COLLECTION_INSTRUMENTS,
            "definitions_found",
            {
                node_id(COLLECTION_INSTRUMENTS, law_key(o)): len(d)
                for o, d in found.items()
            },
            {row["id"]: row["definitions_found"] for row in laws.values()},
        )
        logger.info(
            "Definitions: %d laws of the Staatsblad read, %d definitions.",
            len(found),
            sum(len(d) for d in found.values()),
        )
        return found
