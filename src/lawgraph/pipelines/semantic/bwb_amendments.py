"""Semantic pipeline: amending publications → AMENDS / INTRODUCES / REPEALS → articles.

Everything here is read straight from the BWB XML (as stored by the normalize
pipelines), nothing is guessed:

* every article version says which publication created it (``origin_publication``,
  e.g. ``Stb. 2019, 33``) and what that did (``effect``: nieuw / wijziging /
  vervallen). The publication is an ``Instrument``; the edge goes from it to the
  article identity the version belongs to (``stam-id``), as
  ``AMENDS`` / ``INTRODUCES`` / ``REPEALS`` carrying the effective date and the
  article version;
* a publication (and a regulation) lists the parliamentary dossier(s) of the bill
  behind it, which becomes ``LEGISLATED_IN`` (instrument → dossier) when that
  dossier is in the graph.

Runs after ``bwb`` (articles, article versions) and the Tweede Kamer dossiers.
It streams the article versions ordered by article identity and works in chunks:
per chunk one article lookup, one dossier existence check and bulk writes,
however many versions the chunk holds.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_REPEALS,
)
from lawgraph.core.batching import chunked, chunked_aligned
from lawgraph.core.bwb_xml import (
    EFFECT_AMENDS,
    EFFECT_INTRODUCES,
    EFFECT_REPEALS,
    effect_kind,
    publication_key,
    publication_props,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter, NodeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-amendments"

_RELATION_OF_KIND = {
    EFFECT_INTRODUCES: RELATION_INTRODUCES,
    EFFECT_AMENDS: RELATION_AMENDS,
    EFFECT_REPEALS: RELATION_REPEALS,
}

# Sorted by article identity so that all versions of one article end up in the
# same chunk (needed to keep the earliest effective date per publication).
_VERSIONS_AQL = f"""
FOR v IN {COLLECTION_ARTICLE_VERSIONS}
  FILTER v.props.origin_publication != null AND v.props.stam_id != null
  SORT v.props.bwb_id, v.props.stam_id
  RETURN {{
    key: v._key,
    bwb_id: v.props.bwb_id,
    stam_id: v.props.stam_id,
    effect: v.props.effect,
    valid_from: v.props.valid_from,
    source_publication: v.props.source_publication,
    origin: v.props.origin_publication,
    commencement: v.props.commencement_publication
  }}
"""

# One row per stored article; matched to the wanted (bwb_id, stam_id) pairs in Python.
_ARTICLES_AQL = f"""
FOR a IN {COLLECTION_ARTICLES}
  FILTER a.props.bwb_id IN @bwb_ids AND a.props.stam_id IN @stam_ids
  RETURN {{key: a._key, bwb_id: a.props.bwb_id, stam_id: a.props.stam_id}}
"""

_REGULATIONS_AQL = f"""
FOR i IN {COLLECTION_INSTRUMENTS}
  FILTER i.props.bwb_id != null AND IS_ARRAY(i.props.dossier_numbers)
  FILTER LENGTH(i.props.dossier_numbers) > 0
  RETURN {{key: i._key, dossiers: i.props.dossier_numbers}}
"""


def _instrument_id(key: str) -> str:
    return f"{COLLECTION_INSTRUMENTS}/{key}"


def _article_identity(row: dict[str, Any]) -> Hashable:
    return row.get("bwb_id"), row.get("stam_id")


@dataclass
class _Amendment:
    """The earliest version of an article that a publication touched in one way."""

    version_key: str
    effect: str | None
    effective_date: str | None
    source_publication: str | None

    def is_earlier_than(self, other: _Amendment) -> bool:
        # ISO dates compare as text; an unknown date never beats a known one.
        if self.effective_date is None:
            return False
        return (
            other.effective_date is None or self.effective_date < other.effective_date
        )

    def meta(self) -> dict[str, Any]:
        return {
            "effective_date": self.effective_date,
            "article_version": self.version_key,
            "effect": self.effect,
            "source_publication": self.source_publication,
        }


@dataclass
class _Chunk:
    """What one chunk of versions contributes (publications, dossiers, amendments)."""

    publications: dict[str, dict[str, Any]] = field(default_factory=dict)
    dossiers: dict[str, set[str]] = field(default_factory=dict)
    # (publication key, (bwb_id, stam_id), kind) -> earliest touching version
    amendments: dict[tuple[str, tuple[str, str], str], _Amendment] = field(
        default_factory=dict
    )


class BWBAmendmentsSemanticPipeline(SemanticPipelineBase):
    """Create amendment edges and LEGISLATED_IN edges from the BWB metadata."""

    _CHUNK = 500

    def __init__(self, store: Any) -> None:
        super().__init__(store=store)
        # publication key -> dossier numbers already written this run
        self._known_dossiers: dict[str, set[str]] = {}

    def run(self) -> PipelineResult:
        result = PipelineResult()
        nodes = NodeWriter(self.store)
        edges = EdgeWriter(self.store, what=None)
        self._known_dossiers = {}

        rows = self._track(self.store.query(_VERSIONS_AQL), "article versions")
        for rows_chunk in chunked_aligned(rows, self._CHUNK, _article_identity):
            self._process_versions(rows_chunk, nodes, edges, result)
        self._link_regulation_dossiers(edges)

        edges.flush_into(result)
        logger.info(
            "BWB amendments: %d publications, %s.",
            len(self._known_dossiers),
            result.summary(),
        )
        return result

    # ---------------------------------------------------------------- versions

    def _process_versions(
        self,
        rows: list[dict[str, Any]],
        nodes: NodeWriter,
        edges: EdgeWriter,
        result: PipelineResult,
    ) -> None:
        chunk = _Chunk()
        wanted: dict[tuple[str, str], list[tuple[dict[str, Any], str]]] = {}
        for row in rows:
            self._collect_documents(row, chunk)
            classified = self._classify(row)
            if classified is None:
                result.skipped += 1
                continue
            pair, kind = classified
            wanted.setdefault(pair, []).append((row, kind))

        targets = self._resolve_articles(set(wanted))
        for pair, versions in wanted.items():
            if pair not in targets:
                result.skipped += len(versions)
                continue
            for row, kind in versions:
                self._keep_earliest(chunk, row, pair, kind)

        to_link = self._write_documents(chunk, nodes)
        self._write_amendments(chunk, targets, edges)
        self._write_dossier_links(to_link, edges)

    @staticmethod
    def _classify(row: dict[str, Any]) -> tuple[tuple[str, str], str] | None:
        """``((bwb_id, stam_id), kind)`` when the version has an origin and a known effect."""
        origin = row.get("origin")
        kind = effect_kind(row.get("effect"))
        bwb_id, stam_id = row.get("bwb_id"), row.get("stam_id")
        if not (isinstance(origin, dict) and origin.get("id") and kind):
            return None
        if not (bwb_id and stam_id):
            return None
        return (str(bwb_id), str(stam_id)), kind

    @staticmethod
    def _keep_earliest(
        chunk: _Chunk, row: dict[str, Any], pair: tuple[str, str], kind: str
    ) -> None:
        edge = (publication_key(str(row["origin"]["id"])), pair, kind)
        amendment = _Amendment(
            version_key=row["key"],
            effect=row.get("effect"),
            effective_date=row.get("valid_from"),
            source_publication=row.get("source_publication"),
        )
        current = chunk.amendments.get(edge)
        if current is None or amendment.is_earlier_than(current):
            chunk.amendments[edge] = amendment

    def _resolve_articles(
        self, pairs: set[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        """Article key per ``(bwb_id, stam_id)``: one query for the whole chunk."""
        if not pairs:
            return {}
        rows = self.store.query(
            _ARTICLES_AQL,
            {
                "bwb_ids": sorted({bwb_id for bwb_id, _ in pairs}),
                "stam_ids": sorted({stam_id for _, stam_id in pairs}),
            },
        )
        found: dict[tuple[str, str], str] = {}
        for row in rows:
            pair = (str(row.get("bwb_id")), str(row.get("stam_id")))
            # the IN filters form a cartesian product: keep only the wanted pairs
            if pair in pairs and pair not in found:
                found[pair] = row["key"]
        return found

    # ------------------------------------------------------------ publications

    @staticmethod
    def _collect_documents(row: dict[str, Any], chunk: _Chunk) -> None:
        """Collect origin and commencement publication (merging their dossiers)."""
        for publication in (row.get("origin"), row.get("commencement")):
            if not (isinstance(publication, dict) and publication.get("id")):
                continue
            key = publication_key(str(publication["id"]))
            chunk.publications.setdefault(key, publication_props(publication))
            dossiers = chunk.dossiers.setdefault(key, set())
            dossiers.update(str(d) for d in publication.get("dossiers") or [] if d)

    def _write_documents(self, chunk: _Chunk, nodes: NodeWriter) -> dict[str, set[str]]:
        """Upsert publications that are new this run or learned new dossiers.

        Returns the dossier numbers to link per publication: only those not
        linked earlier in this run.
        """
        to_link: dict[str, set[str]] = {}
        for key, props in chunk.publications.items():
            known = self._known_dossiers.get(key)
            merged = (known or set()) | chunk.dossiers[key]
            if known is not None and merged == known:
                continue
            node_props = dict(props)
            if merged:
                node_props["dossier_numbers"] = sorted(merged)
            nodes.add(
                Node(
                    collection=COLLECTION_INSTRUMENTS,
                    type=NodeType.INSTRUMENT,
                    key=key,
                    labels=["BWB", "Publication"],
                    props=node_props,
                )
            )
            to_link[key] = merged - (known or set())
            self._known_dossiers[key] = merged
        nodes.flush()
        return to_link

    # ------------------------------------------------------------------- edges

    def _write_amendments(
        self,
        chunk: _Chunk,
        targets: dict[tuple[str, str], str],
        edges: EdgeWriter,
    ) -> None:
        for (publication, pair, kind), amendment in chunk.amendments.items():
            edges.add(
                _instrument_id(publication),
                f"{COLLECTION_ARTICLES}/{targets[pair]}",
                _RELATION_OF_KIND[kind],
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta=amendment.meta(),
            )

    def _link_regulation_dossiers(self, edges: EdgeWriter) -> None:
        """Regulation → dossier from ``props.dossier_numbers`` (streamed, in chunks)."""
        rows: Iterable[dict[str, Any]] = self.store.query(_REGULATIONS_AQL)
        for chunk in chunked(rows, self._CHUNK):
            self._write_dossier_links(
                {r["key"]: {str(d) for d in r["dossiers"] if d} for r in chunk}, edges
            )

    def _write_dossier_links(
        self, dossiers_by_instrument: dict[str, set[str]], edges: EdgeWriter
    ) -> None:
        """LEGISLATED_IN for every dossier that exists: one existence check per call."""
        wanted = {
            number: make_node_key(number)
            for numbers in dossiers_by_instrument.values()
            for number in numbers
        }
        if not wanted:
            return
        existing = self.store.existing_keys(COLLECTION_DOSSIERS, set(wanted.values()))
        for instrument, numbers in dossiers_by_instrument.items():
            for number in sorted(numbers):
                if wanted[number] not in existing:
                    continue
                edges.add(
                    _instrument_id(instrument),
                    f"{COLLECTION_DOSSIERS}/{wanted[number]}",
                    RELATION_LEGISLATED_IN,
                    source=SEMANTIC_SOURCE,
                    confidence=1.0,
                    meta={"dossier_number": number},
                )
