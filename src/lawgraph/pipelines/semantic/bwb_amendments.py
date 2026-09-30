"""Semantic pipeline: amending publications → AMENDS / INTRODUCES / REPEALS → articles.

Everything here is read straight from the BWB XML (as stored by the normalize
pipelines), nothing is guessed:

* every article version says which publication created it (``origin_publication``,
  e.g. ``Stb. 2019, 33``) and what that did (``effect``: nieuw / wijziging /
  vervallen). The publication is an ``Instrument``; the edge goes from it to the
  article identity the version belongs to (``stam-id``), as
  ``AMENDS`` / ``INTRODUCES`` / ``REPEALS`` carrying the effective date and the
  article version. A republication (``tekstplaatsing``) changes nothing and has no edge;
  the edges of this step into an article that it no longer derives go;
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
from lawgraph.db import EdgeWriter, NodeWriter, edge_key
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-amendments"

_RELATION_OF_KIND = {
    EFFECT_INTRODUCES: RELATION_INTRODUCES,
    EFFECT_AMENDS: RELATION_AMENDS,
    EFFECT_REPEALS: RELATION_REPEALS,
}


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
        self._removed = 0  # amendment edges no longer derived

    def run(self) -> PipelineResult:
        result = PipelineResult()
        nodes = NodeWriter(self.store)
        edges = EdgeWriter(self.store, what=None)
        self._known_dossiers = {}
        self._removed = 0

        rows = self._track(
            semantic_bwb.amending_article_versions(self.store), "article versions"
        )
        for rows_chunk in chunked_aligned(rows, self._CHUNK, _article_identity):
            self._process_versions(rows_chunk, nodes, edges, result)
        self._link_regulation_dossiers(edges)

        edges.flush_into(result)
        logger.info(
            "%d publications; removed %d amendments no longer derived.",
            len(self._known_dossiers),
            self._removed,
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
        seen: set[tuple[str, str]] = set()
        for row in rows:
            self._collect_documents(row, chunk)
            if row.get("bwb_id") and row.get("stam_id"):
                seen.add((str(row["bwb_id"]), str(row["stam_id"])))
            classified = self._classify(row)
            if classified is None:
                result.skipped += 1
                continue
            pair, kind = classified
            wanted.setdefault(pair, []).append((row, kind))

        # every article of the chunk: also one whose versions no longer make an edge
        targets = self._resolve_articles(seen)
        for pair, versions in wanted.items():
            if pair not in targets:
                result.skipped += len(versions)
                continue
            for row, kind in versions:
                self._keep_earliest(chunk, row, pair, kind)

        to_link = self._write_documents(chunk, nodes)
        kept = self._write_amendments(chunk, targets, edges)
        self._write_dossier_links(to_link, edges)
        self._removed += semantic_edges.remove_edges_to(
            self.store,
            list(_RELATION_OF_KIND.values()),
            SEMANTIC_SOURCE,
            [f"{COLLECTION_ARTICLES}/{key}" for key in targets.values()],
            kept,
        )

    @staticmethod
    def _classify(row: dict[str, Any]) -> tuple[tuple[str, str], str] | None:
        """``((bwb_id, stam_id), kind)`` when the version has an origin and an effect that
        changes the article (not a republication)."""
        origin = row.get("origin")
        kind = effect_kind(row.get("effect"))
        bwb_id, stam_id = row.get("bwb_id"), row.get("stam_id")
        if not (isinstance(origin, dict) and origin.get("id")):
            return None
        if kind not in _RELATION_OF_KIND:
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
        rows = semantic_bwb.articles_by_identity(
            self.store,
            sorted({bwb_id for bwb_id, _ in pairs}),
            sorted({stam_id for _, stam_id in pairs}),
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
    ) -> dict[str, set[str]]:
        """Write the amendments; the keys of the edges per article id."""
        kept: dict[str, set[str]] = {}
        for (publication, pair, kind), amendment in chunk.amendments.items():
            source_id = _instrument_id(publication)
            target_id = f"{COLLECTION_ARTICLES}/{targets[pair]}"
            relation = _RELATION_OF_KIND[kind]
            edges.add(
                source_id,
                target_id,
                relation,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta=amendment.meta(),
            )
            kept.setdefault(target_id, set()).add(
                edge_key(source_id, relation, target_id)
            )
        return kept

    def _link_regulation_dossiers(self, edges: EdgeWriter) -> None:
        """Regulation → dossier from ``props.dossier_numbers`` (streamed, in chunks); the
        edges of this pipeline from a regulation to a dossier it no longer lists go."""
        rows: Iterable[dict[str, Any]] = semantic_bwb.regulation_dossier_numbers(
            self.store
        )
        removed = 0
        for chunk in chunked(rows, self._CHUNK):
            kept = self._write_dossier_links(
                {r["key"]: {str(d) for d in r["dossiers"] if d} for r in chunk}, edges
            )
            removed += semantic_edges.remove_edges_from(
                self.store,
                RELATION_LEGISLATED_IN,
                SEMANTIC_SOURCE,
                [_instrument_id(r["key"]) for r in chunk],
                kept,
            )
        logger.info("Removed %d regulation dossiers the BWB no longer names.", removed)

    def _write_dossier_links(
        self, dossiers_by_instrument: dict[str, set[str]], edges: EdgeWriter
    ) -> dict[str, set[str]]:
        """LEGISLATED_IN for every dossier that exists: one existence check per call.
        Returns the keys of the edges per instrument id."""
        wanted = {
            number: make_node_key(number)
            for numbers in dossiers_by_instrument.values()
            for number in numbers
        }
        if not wanted:
            return {}
        existing = self.store.existing_keys(COLLECTION_DOSSIERS, set(wanted.values()))
        kept: dict[str, set[str]] = {}
        for instrument, numbers in dossiers_by_instrument.items():
            for number in sorted(numbers):
                if wanted[number] not in existing:
                    continue
                source_id = _instrument_id(instrument)
                target_id = f"{COLLECTION_DOSSIERS}/{wanted[number]}"
                edges.add(
                    source_id,
                    target_id,
                    RELATION_LEGISLATED_IN,
                    source=SEMANTIC_SOURCE,
                    confidence=1.0,
                    meta={"dossier_number": number},
                )
                kept.setdefault(source_id, set()).add(
                    edge_key(source_id, RELATION_LEGISLATED_IN, target_id)
                )
        return kept
