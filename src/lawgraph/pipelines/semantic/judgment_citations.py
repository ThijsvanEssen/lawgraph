"""Semantic pipeline that detects ECLI references between judgments (CITES_JUDGMENT)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.settings import COLLECTION_JUDGMENTS, RELATION_CITES_JUDGMENT
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.utils.time import describe_since

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"

# Matches ECLI:NL:HR:2020:1234 and international variants.
_ECLI_PATTERN = re.compile(
    r"\bECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:\d+\b",
    re.IGNORECASE,
)


def detect_ecli_references(text: str | None) -> list[str]:
    """Return unique ECLI identifiers found in text, normalised to upper-case."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _ECLI_PATTERN.finditer(text):
        ecli = match.group(0).upper()
        if ecli not in seen:
            seen.add(ecli)
            result.append(ecli)
    return result


class JudgmentCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create CITES_JUDGMENT edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        judgments = list(self._load_judgments())

        if not judgments:
            logger.debug("No judgments found for ECLI citation linking.")
            return result

        logger.info(
            "Scanning %d judgments for ECLI cross-references (since=%s).",
            len(judgments),
            describe_since(since),
        )

        for doc in judgments:
            judgment = Node.from_document(COLLECTION_JUDGMENTS, doc)
            text = self._extract_text(judgment)
            eclis = detect_ecli_references(text)

            for ecli in eclis:
                # Do not create self-references.
                if ecli.upper() == (judgment.props.get("ecli") or "").upper():
                    continue

                target = self._resolve_or_stub_judgment(ecli)
                if target is None:
                    continue

                created = self._create_semantic_edge(
                    from_node=judgment,
                    to_node=target,
                    relation=RELATION_CITES_JUDGMENT,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={"cited_ecli": ecli},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("Judgment citation linker: %s.", result.summary())
        return result

    def _load_judgments(self) -> Iterable[dict[str, Any]]:
        aql = f"FOR doc IN {COLLECTION_JUDGMENTS} RETURN doc"
        return self.store.query(aql)

    def _resolve_or_stub_judgment(self, ecli: str) -> Node | None:
        """Return the judgment node for *ecli*, creating a stub if it isn't in the DB yet."""
        key = make_node_key(ecli)
        node = self.store.get_node(COLLECTION_JUDGMENTS, key)
        if node is not None:
            return node

        # Try secondary lookup by props.ecli (handles legacy non-deterministic keys).
        aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli == @ecli
            LIMIT 1
            RETURN doc
        """
        for doc in self.store.query(aql, bind_vars={"ecli": ecli}):
            return Node.from_document(COLLECTION_JUDGMENTS, doc)

        # Judgment isn't loaded yet — create a stub so the graph stays connected
        # and the frontend can surface "click here to import this judgment."
        logger.debug("Creating stub judgment for %s", ecli)
        return self.store.ensure_stub_node(
            COLLECTION_JUDGMENTS,
            key,
            NodeType.JUDGMENT,
            props={"ecli": ecli},
        )

    def _extract_text(self, judgment: Node) -> str | None:
        props = judgment.props
        for key in ("raw_xml", "text", "body"):
            value = props.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
