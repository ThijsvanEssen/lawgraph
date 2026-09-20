"""Semantic pipeline: BWB regulation → BASED_ON → the article it is issued under.

The BWB XML states the legal basis in the preamble: the paragraph that starts with
"Gelet op" contains ``<extref bwb-id=… doc="jci1.3:c:BWBR0001947&artikel=125">``
elements. ``core.bwb_xml.parse_toestand`` reads them into ``ToestandXml.basis``;
this pipeline turns each entry that names an article into

    Instrument(regulation) --BASED_ON--> Article(basis regulation, article)

Entries without an article number have no target and are skipped, as are
targets that are not in the graph and references to the regulation itself.

The raw toestand XML (``raw_sources``) is streamed and handled in chunks: per chunk
one existence check for the regulations and one for the target articles.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_BWB_TOESTAND,
    RELATION_BASED_ON,
    SOURCE_BWB,
)
from lawgraph.core.batching import chunked
from lawgraph.core.bwb_xml import BasisRef, parse_toestand
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-grondslagen-linker"

_XML_CHUNK = 50  # toestand XML documents are large; keep few in memory at once

_TOESTAND_AQL = f"""
FOR rs IN {COLLECTION_RAW_SOURCES}
  FILTER rs.source == @source
  FILTER rs.kind == @kind
  FILTER rs.payload_text != null
  RETURN {{
    bwb_id: rs.meta.bwb_id || rs.external_id || rs.identifier,
    xml: rs.payload_text
  }}
"""

# (regulation key, target article key, the "Gelet op" reference)
_Link = tuple[str, str, BasisRef]


class BWBGrondslagenSemanticPipeline(SemanticPipelineBase):
    """Create BASED_ON edges from BWB regulations to their legal-basis articles."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store)
        rows = self.store.query(
            _TOESTAND_AQL,
            {"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
            batch_size=20,  # payloads are full XML documents
        )
        for chunk in chunked(self._track(rows, "BWB toestanden"), _XML_CHUNK):
            self._link_chunk(chunk, edges, result)
        edges.flush()
        result.created += edges.created
        result.updated += edges.updated
        logger.info("BWB grondslagen: %s.", result.summary())
        return result

    def _link_chunk(
        self, rows: list[dict[str, Any]], edges: EdgeWriter, result: PipelineResult
    ) -> None:
        links: list[_Link] = []
        for row in rows:
            found = self._basis_links(row)
            if not found:
                result.skipped += 1
            links.extend(found)
        if not links:
            return

        sources = self.store.existing_keys(
            COLLECTION_INSTRUMENTS, {source for source, _, _ in links}
        )
        targets = self.store.existing_keys(
            COLLECTION_ARTICLES, {target for _, target, _ in links}
        )
        for source, target, ref in links:
            if source not in sources or target not in targets:
                result.skipped += 1
                continue
            edges.add(
                f"{COLLECTION_INSTRUMENTS}/{source}",
                f"{COLLECTION_ARTICLES}/{target}",
                RELATION_BASED_ON,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"text": ref.text, "doc": ref.doc},
            )

    @staticmethod
    def _basis_links(row: dict[str, Any]) -> list[_Link]:
        """Candidate edges of one regulation: basis entries that name an article."""
        xml_text = row.get("xml") or ""
        if not xml_text:
            return []
        try:
            toestand = parse_toestand(xml_text)
        except ET.ParseError as exc:
            logger.warning(
                "BWB grondslagen: unparseable XML for %s: %s", row.get("bwb_id"), exc
            )
            return []
        bwb_id = str(row.get("bwb_id") or toestand.bwb_id or "").upper()
        if not bwb_id:
            return []
        source = make_node_key(bwb_id)
        links: list[_Link] = []
        for ref in toestand.basis:
            if not ref.article or ref.bwb_id.upper() == bwb_id:
                continue  # no target article, or a reference to itself
            links.append((source, make_node_key(ref.bwb_id.upper(), ref.article), ref))
        return links
