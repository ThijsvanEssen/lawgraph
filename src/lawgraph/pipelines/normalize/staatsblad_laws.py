"""Normalize pipeline for the laws of the Staatsblad the BWB does not hold (yet): an
instrument with its articles read from the XML of the publication that enacted it
(``core/staatsblad_laws.py``), with the divisions later laws of the Staatsblad gave a whole new
text in place.

Of every stored law (``retrieve staatsblad``: the laws of the dossiers whose bill passed)
that enacts a law and that the BWB holds no regulation of (``props.enacted_publication``):

* the law ``instruments/wet_stb_2026_56``, its articles ``articles/stb_2026_56_<number>``
  (``official_id`` ``stb-2026-56``), each ``PART_OF`` it;
* each publication its text comes from as an instrument of kind ``publicatie``
  (``instruments/stb_2026_56``, as the BWB names a publication), which ``ESTABLISHES`` the
  articles of the law it enacted and ``INTRODUCES`` those it gave a text.

Every stored law, also one that only changes others and a budget law (whose text is not
read: a law of budget dossiers alone), is a publication (one the graph does not hold yet
written as above) ``LEGISLATED_IN`` the dossiers it names that the graph holds
(``queries/dossier_keys``: a Rijkswet's by its number alone).

The laws are derived in full on every run, whatever ``--since``: a law the BWB holds now
goes with its articles and their edges (its addresses lead to the BWB: ``/render``), and an
article no longer in a law goes. A record of the source is never removed.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_STAATSBLAD_LAW,
    RELATION_ESTABLISHES,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.bwb_xml import publication_props
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.publications import instrument_key, law_key, parse_koop_id
from lawgraph.core.raw_records import payload_text
from lawgraph.core.staatsblad_laws import (
    LawPublication,
    article_props,
    law_props,
    law_text,
    read_records,
)
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries import removals
from lawgraph.db.queries import staatsblad_laws as law_queries
from lawgraph.db.queries.dossier_keys import dossier_keys
from lawgraph.pipelines.normalize.base import NormalizePipelineBase
from lawgraph.sources.addresses import edge_source

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
LABEL = "Staatsblad"


@dataclass
class _Written:
    """What the edges need of the nodes written: the law of each article, the publication
    each article comes from, and the publications with their dossiers."""

    article_law: dict[str, str] = field(default_factory=dict)  # article id -> law id
    article_source: dict[str, str] = field(default_factory=dict)  # article id -> pub id
    enacted_by: dict[str, str] = field(default_factory=dict)  # law id -> its own pub id
    dossiers: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )  # pub id -> labels
    laws: set[str] = field(default_factory=set)  # official ids of the laws written


def _publication_node(publication: LawPublication) -> Node:
    """The publication as the BWB names one (``bwb_xml.publication_props``)."""
    parsed = parse_koop_id(publication.official_id)
    year, number = (parsed[1], parsed[2]) if parsed else (None, None)
    props = publication_props(
        {
            "kind": "Stb",
            "year": year,
            "number": number,
            "url_identifier": publication.official_id,
            "signed": publication.date_signed,
            "published": publication.date_published,
        }
    )
    props["source"] = SOURCE_STAATSBLAD
    props["dossier_numbers"] = list(publication.dossiers)
    return Node(
        collection=COLLECTION_INSTRUMENTS,
        key=instrument_key(publication.official_id),
        labels=[LABEL, "Publication"],
        props=props,
    )


def _text_wanted(publication: LawPublication, budgets: set[str]) -> bool:
    """Whether the text of *publication* is read: it enacts a law or gives one a new text,
    and is not a budget law (a law of *budgets* alone)."""
    if publication.dossiers and set(publication.dossiers) <= budgets:
        return False
    return publication.enacts_a_law or bool(publication.replacements)


class StaatsbladLawsNormalizePipeline(NormalizePipelineBase[list[LawPublication]]):
    """The laws of the Staatsblad the BWB does not hold (yet), as instruments with their
    articles."""

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[LawPublication]:
        """Every stored law, whatever *since*: the laws are derived in full, and a later law
        may give an earlier one a new text (a few records, read whole)."""
        records = (
            (record.get("external_id"), payload_text(record))
            for record in self._iter_raw_sources(
                source=SOURCE_STAATSBLAD, kinds=[RAW_KIND_STAATSBLAD_LAW]
            )
        )
        budgets = law_queries.budget_dossiers(self.store)
        found, skipped = read_records(
            records, text_wanted=lambda p: _text_wanted(p, budgets)
        )
        for why, official in skipped:
            self.progress.skip(why, official)
        return found

    def write(self, raw: list[LawPublication], result: PipelineResult) -> None:
        laws = [p for p in raw if p.enacts_a_law]
        in_bwb = law_queries.enacted_in_the_bwb(
            self.store, [p.official_id for p in laws]
        )
        for official, bwb_id in sorted(in_bwb.items()):
            logger.info("%s: the BWB holds it as %s; its law goes.", official, bwb_id)
        written = self._write_nodes(
            [p for p in laws if p.official_id not in in_bwb], raw
        )
        self._write_publications(raw, written)
        self._remove_gone(written)
        self._link(written)

    def _write_nodes(
        self, laws: list[LawPublication], publications: list[LawPublication]
    ) -> _Written:
        written = _Written()
        by_id = {p.official_id: p for p in publications}
        with NodeWriter(self.store) as writer:
            for law in laws:
                text = law_text(law, publications)
                for official, path in text.not_found:
                    self.progress.note(
                        "a division another law gives a new text is not in the law",
                        f"{official} {law.official_id} {path}",
                    )
                sources = [law.official_id] + [
                    s
                    for s in dict.fromkeys(a.source or "" for a in text.articles)
                    if s in by_id and s != law.official_id
                ]
                dossiers = list(
                    dict.fromkeys(d for s in sources for d in by_id[s].dossiers)
                )
                law_node = Node(
                    collection=COLLECTION_INSTRUMENTS,
                    key=law_key(law.official_id),
                    labels=[LABEL],
                    props=law_props(law, dossiers),
                )
                writer.add(law_node)
                written.laws.add(law.official_id)
                law_id = node_id(COLLECTION_INSTRUMENTS, law_key(law.official_id))
                for source in sources:
                    publication = _publication_node(by_id[source])
                    writer.add(publication)
                    written.dossiers[
                        node_id(COLLECTION_INSTRUMENTS, str(publication.key))
                    ] = by_id[source].dossiers
                written.enacted_by[law_id] = node_id(
                    COLLECTION_INSTRUMENTS, instrument_key(law.official_id)
                )
                for position, article in enumerate(text.articles):
                    if not article.number:
                        continue
                    key = make_node_key(law.official_id, article.number)
                    writer.add(
                        Node(
                            collection=COLLECTION_ARTICLES,
                            key=key,
                            labels=[LABEL, "Article"],
                            props=article_props(article, law, position),
                        )
                    )
                    article_id = node_id(COLLECTION_ARTICLES, key)
                    written.article_law[article_id] = law_id
                    written.article_source[article_id] = node_id(
                        COLLECTION_INSTRUMENTS,
                        instrument_key(article.source or law.official_id),
                    )
        return written

    def _write_publications(
        self, publications: list[LawPublication], written: _Written
    ) -> None:
        """The publication of every other law, for its dossiers: one the graph does not
        hold yet (the BWB names most) as the BWB names a publication."""
        rest = {
            instrument_key(p.official_id): p
            for p in publications
            if node_id(COLLECTION_INSTRUMENTS, instrument_key(p.official_id))
            not in written.dossiers
        }
        held = self.store.existing_keys(COLLECTION_INSTRUMENTS, set(rest))
        with NodeWriter(self.store) as writer:
            for key, publication in rest.items():
                if key not in held:
                    writer.add(_publication_node(publication))
                written.dossiers[node_id(COLLECTION_INSTRUMENTS, key)] = (
                    publication.dossiers
                )

    def _remove_gone(self, written: _Written) -> None:
        """The laws not written (the BWB holds them now), and the articles of a law it no
        longer holds, with their edges."""
        gone_laws = [
            str(key)
            for key in law_queries.law_keys(self.store)
            if key not in {law_key(o) for o in written.laws}
        ]
        gone_articles = [
            row["key"]
            for row in law_queries.law_article_keys(self.store)
            if node_id(COLLECTION_ARTICLES, row["key"]) not in written.article_law
        ]
        if gone_laws or gone_articles:
            logger.info(
                "%d laws and %d articles no longer read from the Staatsblad removed.",
                removals.remove_nodes(self.store, COLLECTION_INSTRUMENTS, gone_laws),
                removals.remove_nodes(self.store, COLLECTION_ARTICLES, gone_articles),
            )

    def _link(self, written: _Written) -> None:
        """PART_OF from each article to its law; ESTABLISHES from the publication that
        enacted the law to each article of its own, INTRODUCES from a later publication to
        each article it gave a text; LEGISLATED_IN from each publication to its dossiers in
        the graph. An edge of this step from these nodes that is not written again goes."""
        held = dossier_keys(
            self.store, {d for ds in written.dossiers.values() for d in ds}
        )
        with EdgeWriter(self.store, what="law edges", remembers=True) as edges:
            for article_id, law_id in sorted(written.article_law.items()):
                edges.add(article_id, law_id, RELATION_PART_OF, source=EDGE_SOURCE)
                source = written.article_source[article_id]
                relation = (
                    RELATION_ESTABLISHES
                    if source == written.enacted_by[law_id]
                    else RELATION_INTRODUCES
                )
                edges.add(source, article_id, relation, source=EDGE_SOURCE)
            for publication_id, dossiers in sorted(written.dossiers.items()):
                for dossier in dossiers:
                    if dossier in held:
                        edges.add(
                            publication_id,
                            node_id(COLLECTION_DOSSIERS, held[dossier]),
                            RELATION_LEGISLATED_IN,
                            source=EDGE_SOURCE,
                        )
        self._remove_stale(edges, written)

    @staticmethod
    def _remove_stale(edges: EdgeWriter, written: _Written) -> None:
        publications = sorted(written.dossiers)
        removed = edges.remove_stale(
            RELATION_PART_OF, EDGE_SOURCE, sorted(written.article_law)
        )
        for relation in (
            RELATION_ESTABLISHES,
            RELATION_INTRODUCES,
            RELATION_LEGISLATED_IN,
        ):
            removed += edges.remove_stale(relation, EDGE_SOURCE, publications)
        if removed:
            logger.info("%d edges no longer derived removed.", removed)
