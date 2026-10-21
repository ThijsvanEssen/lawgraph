from __future__ import annotations

import datetime as dt
import hashlib
import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    RAW_KIND_TOOI_THESAURUS,
    RELATION_PART_OF,
    SOURCE_BWB,
    SOURCE_TOOI,
    TOOI_BWB_LEGAL_AREAS,
    TOOI_BWB_THEMES,
)
from lawgraph.core.aliases import abbreviation_of, curated_abbreviations
from lawgraph.core.annex_xml import ANNEX_EDGE_SOURCE, annex_node_key
from lawgraph.core.batching import chunked
from lawgraph.core.bwb_wti import (
    Concepts,
    choose_short_titles,
    instrument_aliases,
    label_concepts,
    parse_abbreviations,
    parse_citation_titles,
    parse_subjects,
    thesaurus_concepts,
    with_concepts,
)
from lawgraph.core.bwb_xml import (
    annex_keys,
    annex_props,
    article_key,
    article_props,
    celex_refs,
    expiry_date,
    instrument_props,
    parse_toestand,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import state as state_queries
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

EDGE_SOURCE = "bwb-normalize"
# Only the current toestand: the historical ones (``bwb-toestand-xml-all``) carry the same
# bwb_id and would overwrite the articles of today with those of whichever came last.
TOESTAND_KINDS = [RAW_KIND_BWB_TOESTAND]
SHORT_TITLE_BATCH_SIZE = 1000
# ``pipeline_state``: the digest of what the WTI pass read besides the WTI records (the
# curated abbreviations, the TOOI thesauri) when it last ran
WTI_PASS_STATE = "normalize bwb wti"


@dataclass(frozen=True)
class Written:
    """What the edges need of the nodes written: per regulation its instrument, the keys
    of its articles and those of its annexes."""

    instruments: dict[str, Node] = field(default_factory=dict)
    articles: dict[str, list[str]] = field(default_factory=dict)
    annexes: dict[str, list[str]] = field(default_factory=dict)


class BWBNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalize BWB XML into Instrument and Article nodes, with their short titles."""

    _since: dt.datetime | None = None

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        self._since = since
        return super().run(since=since)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the BWB raw_sources records relevant to instrument/article parsing."""
        return self._iter_raw_sources(
            source=SOURCE_BWB, kinds=TOESTAND_KINDS, since=since
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The nodes of every toestand and the short titles, then their edges."""
        self._link(self._write_nodes(raw, result))

    def _write_nodes(self, raw: Records, result: PipelineResult) -> Written:
        """Parse the current BWB toestand of each regulation into Instrument and Article nodes."""
        written = Written()
        article_count = 0

        with NodeWriter(self.store) as writer:
            for record in raw:
                text = payload_text(record)
                bwb_id = meta(record).get("bwb_id") or record.get("external_id")
                if not text or not bwb_id:
                    self.progress.skip("no payload or BWB id", record.get("key"))
                    continue
                try:
                    toestand = parse_toestand(text)
                except ET.ParseError as exc:
                    self.progress.fail("toestand not XML", f"{bwb_id}: {exc}")
                    continue

                instrument = written.instruments.get(bwb_id)
                if instrument is None:
                    props = instrument_props(
                        toestand,
                        bwb_id,
                        celex_refs=celex_refs(text),
                        date_expired=expiry_date(
                            meta(record).get("end_date"), record.get("fetched_at")
                        ),
                    )
                    # Through the writer, like the articles: one request per regulation
                    # was 42,000 round trips, and a write also when nothing changed.
                    instrument = Node(
                        collection=COLLECTION_INSTRUMENTS,
                        key=make_node_key(bwb_id),
                        labels=["BWB"],
                        props=props,
                    )
                    writer.add(instrument)
                    written.instruments[bwb_id] = instrument

                annexes = annex_keys(toestand, bwb_id)
                for place, annex in enumerate(toestand.annexes):
                    key = annex_node_key(bwb_id, annex.label)
                    writer.add(
                        Node(
                            collection=COLLECTION_ANNEXES,
                            key=key,
                            labels=["BWB", "Annex"],
                            props=annex_props(
                                annex,
                                bwb_id,
                                instrument.props.get("citation_title"),
                                place,
                                annexes=annexes,
                            ),
                        )
                    )
                    written.annexes.setdefault(bwb_id, []).append(key)

                for position, article in enumerate(toestand.articles):
                    found_key = article_key(bwb_id, article.number, article.stam_id)
                    if found_key is None or not article.text:
                        logger.debug(
                            "Skipping article without number, stam-id or text in %s.",
                            bwb_id,
                        )
                        continue
                    props = article_props(
                        article,
                        bwb_id,
                        instrument.props.get("citation_title"),
                        position,
                        annexes=annexes,
                    )
                    key = found_key
                    writer.add(
                        Node(
                            collection=COLLECTION_ARTICLES,
                            key=key,
                            labels=["BWB", "Article"],
                            props=props,
                        )
                    )
                    # the edges only need the key
                    written.articles.setdefault(bwb_id, []).append(key)
                    article_count += 1

        logger.info(
            "Normalized %d BWB articles for %d instruments.",
            article_count,
            len(written.instruments),
        )
        thesauri = self._thesauri()
        digest = _digest(curated_abbreviations(), thesauri)
        if self._wti_pass_needed(digest):
            self._write_abbreviations(result, thesauri)
            state_queries.set_state(self.store, WTI_PASS_STATE, {"inputs": digest})
        else:
            logger.info("BWB short titles: no new WTI record, node or list; kept.")
        return written

    def _wti_pass_needed(self, digest: str) -> bool:
        """Whether the WTI pass can change anything: always in a run in full; in a run
        ``--since`` when a WTI record was fetched since, the toestanden created a node
        (whose short title or abbreviation it sets), or the curated abbreviations or the
        thesauri differ from those of the last pass."""
        since = iso_timestamp(self._since)
        if since is None or self.store.writes.nodes_created:
            return True
        last = state_queries.get_state(self.store, WTI_PASS_STATE) or {}
        return last.get("inputs") != digest or raw_queries.fetched_since(
            self.store,
            source=SOURCE_BWB,
            kinds=[RAW_KIND_BWB_WTI_GENERAL],
            since_iso=since,
        )

    def _link(self, written: Written) -> None:
        """PART_OF from every article and annex to its instrument."""
        writer = EdgeWriter(self.store, what="article and annex edges")
        for bwb_id, instrument in written.instruments.items():
            for article in written.articles.get(bwb_id, []):
                writer.add(
                    node_id(COLLECTION_ARTICLES, article),
                    instrument.node_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
            for annex_key in written.annexes.get(bwb_id, []):
                writer.add(
                    node_id(COLLECTION_ANNEXES, annex_key),
                    instrument.node_id,
                    RELATION_PART_OF,
                    source=ANNEX_EDGE_SOURCE,
                    confidence=1.0,
                )
        writer.flush()

    def _write_instrument_abbreviations(
        self,
        abbreviations_by_bwb: dict[str, list[str]],
        short_titles: Mapping[str, str | None],
    ) -> int:
        """``abbreviation`` on every instrument the WTI or the curated list names
        (``abbreviation_of``: the WTI short title, else the first curated one: EVRM, AVG),
        and on their articles as ``instrument_abbreviation``; how many nodes changed."""
        curated = curated_abbreviations()
        laws = {law_id.upper() for law_id in (*abbreviations_by_bwb, *curated)}
        rows = [
            {
                "key": make_node_key(law_id),
                "abbreviation": abbreviation_of(
                    law_id, short_titles.get(law_id), curated
                ),
            }
            for law_id in sorted(laws)
        ]
        return sum(
            normalize_bwb.update_instrument_abbreviations(self.store, batch)
            for batch in chunked(rows, SHORT_TITLE_BATCH_SIZE)
        )

    def _thesauri(self) -> tuple[Concepts, Concepts]:
        """The concepts of the TOOI thesauri of the legal areas and the government themes
        (``retrieve tooi``), by label; empty when they were not retrieved."""
        found: dict[str, Concepts] = {}
        for record in self._iter_raw_sources(
            source=SOURCE_TOOI, kinds=[RAW_KIND_TOOI_THESAURUS]
        ):
            items = payload_json(record).get("items")
            found[str(record.get("external_id"))] = thesaurus_concepts(items or [])
        return found.get(TOOI_BWB_LEGAL_AREAS, {}), found.get(TOOI_BWB_THEMES, {})

    def _subject_rows(
        self,
        parsed: dict[str, tuple[list[dict[str, Any]], list[str]]],
        thesauri: tuple[Concepts, Concepts],
    ) -> list[dict[str, Any]]:
        """``{key, legal_areas, policy_domains}`` per regulation, with the concepts of the
        TOOI thesauri; without them, concepts made from the labels of every regulation
        (slugs unique over the whole list either way)."""
        legal_areas, themes = thesauri
        if not legal_areas:
            legal_areas = label_concepts(
                pair
                for areas, _ in parsed.values()
                for area in areas
                for pair in (
                    (area["main"], None),
                    *([(area["specific"], area["main"])] if area["specific"] else []),
                )
            )
        if not themes:
            themes = label_concepts(
                (domain, None) for _, domains in parsed.values() for domain in domains
            )
        rows = []
        for bwb_id, (areas, domains) in parsed.items():
            with_areas, with_domains = with_concepts(
                areas, domains, legal_areas, themes
            )
            rows.append(
                {
                    "key": make_node_key(bwb_id),
                    "legal_areas": with_areas,
                    "policy_domains": with_domains,
                }
            )
        return rows

    def _write_abbreviations(
        self, result: PipelineResult, thesauri: tuple[Concepts, Concepts]
    ) -> None:
        """Set ``short_title`` and ``aliases`` on the instruments from the official WTI
        abbreviations (``aliases`` also for the books of a code, ``instrument_aliases``), and
        ``citation_titles``: every citation title the WTI gives, the earlier ones too.

        Which abbreviation wins depends on what the other regulations claim
        (``choose_short_titles``), so every stored WTI record is read, whatever ``since``
        is; the records are about 1 KB each. A regulation without a
        winning abbreviation loses a short title it had. Instruments that do not exist
        are not created.
        """
        abbreviations_by_bwb: dict[str, list[str]] = {}
        titles_by_bwb: dict[str, list[str]] = {}
        parsed: dict[str, tuple[list[dict[str, Any]], list[str]]] = {}
        for record in self._iter_raw_sources(
            source=SOURCE_BWB, kinds=[RAW_KIND_BWB_WTI_GENERAL]
        ):
            bwb_id = meta(record).get("bwb_id") or record.get("external_id")
            text = payload_text(record)
            if not bwb_id or not text:
                self.progress.skip("no WTI payload or BWB id", record.get("key"))
                continue
            try:
                abbreviations_by_bwb[bwb_id] = parse_abbreviations(text)
                titles_by_bwb[bwb_id] = parse_citation_titles(text)
                parsed[bwb_id] = parse_subjects(text)
            except ET.ParseError as exc:
                self.progress.fail("WTI not XML", f"{bwb_id}: {exc}")

        short_titles = choose_short_titles(abbreviations_by_bwb)
        rows = [
            {
                "key": make_node_key(bwb_id),
                "short_title": short_titles.get(bwb_id),
                "aliases": aliases,
                "citation_titles": titles_by_bwb.get(bwb_id) or [],
            }
            for bwb_id, aliases in instrument_aliases(abbreviations_by_bwb).items()
        ]
        changed = 0
        for batch in chunked(rows, SHORT_TITLE_BATCH_SIZE):
            changed += normalize_bwb.update_abbreviations(self.store, batch)
        changed += self._write_instrument_abbreviations(
            abbreviations_by_bwb, short_titles
        )
        for batch in chunked(
            self._subject_rows(parsed, thesauri), SHORT_TITLE_BATCH_SIZE
        ):
            changed += normalize_bwb.update_subjects(self.store, batch)
        # The SQL update bypasses the counting store's upsert methods, so add it here.
        result.updated += changed
        logger.info(
            "BWB short titles and aliases: %d regulations, %d with a short title, "
            "%d instruments changed.",
            len(rows),
            sum(1 for row in rows if row["short_title"]),
            changed,
        )


def _digest(*inputs: object) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
