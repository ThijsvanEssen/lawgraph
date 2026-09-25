"""Normalize every historical BWB toestand into versions.

Model:

* an **Article** is one identity (BWB ``stam-id``) that keeps its identity across
  versions and renumbering;
* an **ArticleVersion** exists once per real change (``stam-id`` + ``versie-id``),
  not once per toestand — a toestand only *repeats* the versions still valid;
* ``valid_from`` is the article's own ``inwerking`` date and ``valid_until`` is
  the ``valid_from`` of the next version of the same article (null = current),
  so "the instrument on date X" is a date query and needs no membership edges.
  Every period is half-open: ``valid_until`` is the first day the version no longer
  holds; a toestand's inclusive end date becomes the day after it;
* an identity without a ``stam-id`` (an article of a bijlage) is followed by its number;
* at most one version of an article holds on a date (``valid_until_by_key``):
  - a version that says the article lapsed ("Vervallen") holds on no date: it ends the
    article on its ``valid_from``;
  - the last version of an article that is absent from a later toestand (it left the law:
    the old inheritance law of BW Boek 4 in 2003) ends when the first toestand without it
    starts; ``last_seen`` on a version is the start of the latest toestand holding it;
  - a toestand from before an article's commencement shows it as "Dit onderdeel is nog
    niet inwerking getreden", under the versie-id its text will have: that placeholder is
    written only while no toestand gave the text, and never replaces it.

Phase 1 streams the raw XML and writes nodes in blocks; phase 2 (``build_edges``)
finalises ``valid_until`` from the database (so incremental runs stay correct),
links each new version to its Article and each toestand to its Instrument.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND_ALL,
    RELATION_VERSION_OF,
    SOURCE_BWB,
)
from lawgraph.core.batching import chunked
from lawgraph.core.bwb_xml import (
    ArticleXml,
    ToestandXml,
    article_display_name,
    article_label,
    article_version_key,
    article_version_props,
    historical_article_key,
    instrument_props,
    parse_toestand,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

_OPEN_ENDED_DATE = "9999-12-31"
# What a toestand shows for an article before its commencement.
_PLACEHOLDER = re.compile(r"^\s*Dit onderdeel is nog niet in\s*werking getreden", re.I)
_LAPSED = re.compile(r"^\s*Vervallen\b", re.I)
EDGE_SOURCE = "bwb-history-normalize"
_INSTRUMENT_CHUNK = 200  # regulations per finalisation query

WrittenVersions = dict[str, list[tuple[str, str | None]]]  # bwb_id -> [(key, stam_id)]


def is_placeholder(text: str | None) -> bool:
    """Whether an article's text only announces it: "nog niet inwerking getreden"."""
    return bool(_PLACEHOLDER.match(text or ""))


def is_lapsed(effect: str | None, text: str | None) -> bool:
    """Whether a version says its article lapsed: effect ``vervallen`` or the text
    "Vervallen"."""
    return (effect or "").lower() == "vervallen" or bool(_LAPSED.match(text or ""))


def _identity(version: dict[str, Any]) -> tuple[str, str]:
    """The article a version belongs to: its ``stam-id``, else its number."""
    if version.get("stam_id"):
        return version["bwb_id"], version["stam_id"]
    return version["bwb_id"], f"n{version.get('number') or version['key']}"


def valid_until_by_key(
    versions: Iterable[dict[str, Any]],
    starts: dict[str, list[str]] | None = None,
) -> dict[str, str | None]:
    """Expected ``valid_until`` per version key (see the module docstring).

    *versions* are ``{key, bwb_id, stam_id, number, valid_from, last_seen, lapsed}``;
    *starts* the sorted start dates of the toestanden of each law. Within one article
    a version ends where the next begins; a lapsed version ends where it begins; the last
    one ends at the first toestand after its ``last_seen``, else it is current (None).
    """
    chains: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for version in versions:
        chains[_identity(version)].append(version)
    result: dict[str, str | None] = {}
    for (bwb_id, _), chain in chains.items():
        chain.sort(key=lambda v: (v.get("valid_from") or "", v["key"]))
        for version, following in zip(chain, [*chain[1:], None], strict=True):
            if version.get("lapsed"):
                result[version["key"]] = version.get("valid_from")
            elif following is not None:
                result[version["key"]] = following.get("valid_from") or None
            else:
                result[version["key"]] = _first_start_after(
                    (starts or {}).get(bwb_id, []), version.get("last_seen")
                )
    return result


def _first_start_after(starts: list[str], day: str | None) -> str | None:
    """The first toestand start after *day*: when a law went on without the article."""
    if not day:
        return None
    return next((start for start in starts if start > day), None)


def exclusive_end(end_date: str | None) -> str | None:
    """A toestand's inclusive end date as the first day it no longer holds; null for an
    open one."""
    if not end_date or end_date == _OPEN_ENDED_DATE:
        return None
    try:
        return (dt.date.fromisoformat(end_date) + dt.timedelta(days=1)).isoformat()
    except ValueError:
        return None


class BWBHistoryNormalizePipeline(NormalizePipelineBase):
    """Normalize all historical BWB toestanden into instrument and article versions."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the raw historical toestanden (each is a large XML document)."""
        return self._iter_raw_sources(
            source=SOURCE_BWB, kinds=[RAW_KIND_BWB_TOESTAND_ALL], since=since
        )

    # ── phase 1: stream nodes ────────────────────────────────────────────────

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Write instrument versions and article versions; remember what was written."""
        instrument_seed: dict[str, dict[str, Any]] = {}  # bwb_id -> instrument props
        instrument_versions: list[tuple[str, str]] = []  # (bwb_id, version key)
        seen: set[str] = set()  # versions written with their text
        announced: set[str] = set()  # versions written as a placeholder only
        last_seen: dict[str, str] = {}  # version -> the latest toestand holding it
        written: WrittenVersions = defaultdict(list)

        with NodeWriter(self.store) as writer:
            for record in raw:
                parsed = self._parse_record(record)
                if parsed is None:
                    continue
                bwb_id, start_date, end_date, toestand = parsed
                instrument_seed.setdefault(bwb_id, instrument_props(toestand, bwb_id))

                version_key = make_node_key(bwb_id, start_date)
                writer.add(
                    self._instrument_version(
                        version_key, bwb_id, start_date, end_date, self._meta(record)
                    )
                )
                instrument_versions.append((bwb_id, version_key))

                for position, article in enumerate(toestand.articles):
                    key = self._version_key(article, bwb_id, start_date)
                    if key is None:
                        continue
                    last_seen[key] = max(last_seen.get(key, ""), start_date)
                    placeholder = is_placeholder(article.text)
                    if key in seen or (placeholder and key in announced):
                        continue
                    if key not in announced:
                        written[bwb_id].append((key, article.stam_id))
                    (announced if placeholder else seen).add(key)
                    writer.add(
                        self._article_version(
                            key, article, bwb_id, start_date, toestand, position
                        )
                    )

        logger.info(
            "Normalized %d toestanden and %d article versions for %d instruments.",
            len(instrument_versions),
            len(seen),
            len(instrument_seed),
        )
        return {
            "instrument_seed": instrument_seed,
            "instrument_versions": instrument_versions,
            "written": written,
            "last_seen": last_seen,
        }

    def _parse_record(
        self, record: dict[str, Any]
    ) -> tuple[str, str, str | None, ToestandXml] | None:
        payload_text = self._payload_text(record)
        meta = self._meta(record)
        bwb_id = meta.get("bwb_id") or (record.get("external_id") or "").split("@")[0]
        if not payload_text or not bwb_id:
            logger.warning(
                "BWB history record %s unusable; skipping.", record.get("_key")
            )
            return None
        try:
            toestand = parse_toestand(payload_text)
        except ET.ParseError as exc:
            logger.warning("XML parsing failed for BWB history %s: %s", bwb_id, exc)
            return None
        return (
            bwb_id,
            meta.get("start_date") or "unknown",
            meta.get("end_date"),
            toestand,
        )

    @staticmethod
    def _instrument_version(
        key: str,
        bwb_id: str,
        start_date: str,
        end_date: str | None,
        meta: dict[str, Any],
    ) -> Node:
        return Node(
            collection=COLLECTION_INSTRUMENT_VERSIONS,
            type=NodeType.INSTRUMENT_VERSION,
            key=key,
            labels=["BWB", "Version"],
            props={
                "bwb_id": bwb_id,
                "valid_from": start_date,
                "valid_until": exclusive_end(end_date),
                "current": end_date == _OPEN_ENDED_DATE,
                "state_url": meta.get("state_url"),
            },
        )

    @staticmethod
    def _article_version(
        key: str,
        article: ArticleXml,
        bwb_id: str,
        start_date: str,
        toestand: ToestandXml,
        position: int,
    ) -> Node:
        props = article_version_props(
            article, bwb_id, toestand.citation_title, position
        )
        props.setdefault("valid_from", start_date)
        props["current"] = (
            True  # until a later version is found (finalised in build_edges)
        )
        props["last_seen"] = start_date  # raised in build_edges
        return Node(
            collection=COLLECTION_ARTICLE_VERSIONS,
            type=NodeType.ARTICLE_VERSION,
            key=key,
            labels=["BWB", "ArticleVersion"],
            props=props,
        )

    @staticmethod
    def _version_key(article: ArticleXml, bwb_id: str, start_date: str) -> str | None:
        """Key of an article version; falls back to number + date when ids are missing."""
        if article.stam_id and article.versie_id:
            return article_version_key(bwb_id, article.stam_id, article.versie_id)
        if article.number:
            return article_version_key(
                bwb_id, f"n{article.number}", article.valid_from or start_date
            )
        return None

    # ── phase 2: finalise, link ──────────────────────────────────────────────

    def build_edges(self, raw: Any, normalized: dict[str, Any]) -> None:
        """Finalise ``valid_until``, ensure instruments/articles and write VERSION_OF."""
        seed: dict[str, dict[str, Any]] = normalized["instrument_seed"]
        written: WrittenVersions = normalized["written"]

        writer = EdgeWriter(self.store, what="version edges")
        for bwb_id, version_key in normalized["instrument_versions"]:
            writer.add(
                f"{COLLECTION_INSTRUMENT_VERSIONS}/{version_key}",
                f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}",
                RELATION_VERSION_OF,
                source=EDGE_SOURCE,
            )

        for bwb_ids in chunked(sorted(seed), _INSTRUMENT_CHUNK):
            self._ensure_instruments(bwb_ids, seed)
            self._finalise_chunk(bwb_ids, written, normalized["last_seen"], writer)

        writer.flush()
        logger.info(
            "BWB history: %d VERSION_OF edges.", writer.created + writer.updated
        )

    def _ensure_instruments(
        self, bwb_ids: list[str], seed: dict[str, dict[str, Any]]
    ) -> None:
        """Create instruments that do not exist yet (``normalize bwb`` owns the rest)."""
        by_key = {make_node_key(b): b for b in bwb_ids}
        missing = set(by_key) - self.store.existing_keys(COLLECTION_INSTRUMENTS, by_key)
        self._upsert_nodes(
            Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=key,
                labels=["BWB"],
                props=seed[by_key[key]],
            )
            for key in missing
        )

    def _finalise_chunk(
        self,
        bwb_ids: list[str],
        written: WrittenVersions,
        last_seen: dict[str, str],
        writer: EdgeWriter,
    ) -> None:
        versions = list(normalize_queries.article_versions(self.store, bwb_ids))
        for v in versions:
            v["last_seen"] = max(v.get("last_seen") or "", last_seen.get(v["key"], ""))
            v["lapsed"] = is_lapsed(v.get("effect"), v.get("text_start"))
        starts = normalize_queries.toestand_starts(self.store, bwb_ids)
        expected = valid_until_by_key(versions, starts)
        self._write_valid_until(
            [
                v
                for v in versions
                if v.get("valid_until") != expected[v["key"]]
                or v.get("current") is not (expected[v["key"]] is None)
                or v["key"] in last_seen
            ],
            expected,
        )

        article_by_identity = {
            (a["bwb_id"], a["stam_id"]): a["key"]
            for a in normalize_queries.article_identities(self.store, bwb_ids)
            if a.get("stam_id")
        }
        newest = self._newest_per_identity(versions)

        historical: list[Node] = []
        for bwb_id in bwb_ids:
            for version_key, stam_id in written.get(bwb_id, []):
                if not stam_id:
                    continue
                article_key = article_by_identity.get((bwb_id, stam_id))
                if article_key is None:
                    row = newest[(bwb_id, stam_id)]
                    article_key = historical_article_key(
                        bwb_id, row.get("number"), stam_id
                    )
                    article_by_identity[(bwb_id, stam_id)] = article_key
                    historical.append(self._historical_article(article_key, row))
                writer.add(
                    f"{COLLECTION_ARTICLE_VERSIONS}/{version_key}",
                    f"{COLLECTION_ARTICLES}/{article_key}",
                    RELATION_VERSION_OF,
                    source=EDGE_SOURCE,
                )
        self._upsert_nodes(historical)

    @staticmethod
    def _newest_per_identity(
        versions: Iterable[dict[str, Any]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        newest: dict[tuple[str, str], dict[str, Any]] = {}
        for v in versions:
            if not v.get("stam_id"):
                continue
            ident = (v["bwb_id"], v["stam_id"])
            if ident not in newest or (v.get("valid_from") or "") >= (
                newest[ident].get("valid_from") or ""
            ):
                newest[ident] = v
        return newest

    @staticmethod
    def _historical_article(key: str, row: dict[str, Any]) -> Node:
        """An article identity that is no longer in the current toestand, named by its
        newest version."""
        number, title = row.get("number"), row.get("title")
        label = row.get("label") or (article_label(number) if number else None)
        return Node(
            collection=COLLECTION_ARTICLES,
            type=NodeType.ARTICLE,
            key=key,
            labels=["BWB", "Article"],
            props={
                "bwb_id": row["bwb_id"],
                # not `article_number`: (bwb_id, article_number) is a unique index and the
                # number may have been reused by a current article
                "last_article_number": number,
                "label": label,
                "stam_id": row["stam_id"],
                "display_name": article_display_name(label, title),
                "instrument_citation_title": title,
                "repealed": True,
                "source": SOURCE_BWB,
            },
        )

    def _write_valid_until(
        self, stale: list[dict[str, Any]], expected: dict[str, str | None]
    ) -> None:
        """Write ``valid_until`` and ``current`` of the versions where either differs.

        Phase 1 writes every version it reads as current, also one that a later version
        already ended, so ``current`` is checked on its own.
        """
        docs = [
            {
                "_key": v["key"],
                "type": NodeType.ARTICLE_VERSION.value,
                "labels": [],
                "props": {
                    "valid_until": expected[v["key"]],
                    "current": expected[v["key"]] is None,
                    "last_seen": v["last_seen"] or None,
                },
            }
            for v in stale
        ]
        for block in chunked(docs, 500):
            self.store.bulk_insert_or_update_nodes(COLLECTION_ARTICLE_VERSIONS, block)
