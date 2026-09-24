"""Normalize every historical BWB toestand into versions.

Model:

* an **Article** is one identity (BWB ``stam-id``) that keeps its identity across
  versions and renumbering;
* an **ArticleVersion** exists once per real change (``stam-id`` + ``versie-id``),
  not once per toestand — a toestand only *repeats* the versions still valid;
* ``valid_from`` is the article's own ``inwerking`` date and ``valid_until`` is
  the ``valid_from`` of the next version of the same article (null = current),
  so "the instrument on date X" is a date query and needs no membership edges.

Phase 1 streams the raw XML and writes nodes in blocks; phase 2 (``build_edges``)
finalises ``valid_until`` from the database (so incremental runs stay correct),
links each new version to its Article and each toestand to its Instrument.
"""

from __future__ import annotations

import datetime as dt
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
EDGE_SOURCE = "bwb-history-normalize"
_INSTRUMENT_CHUNK = 200  # regulations per finalisation query

WrittenVersions = dict[str, list[tuple[str, str | None]]]  # bwb_id -> [(key, stam_id)]


def valid_until_by_key(versions: Iterable[dict[str, Any]]) -> dict[str, str | None]:
    """Expected ``valid_until`` per version key: the next version's ``valid_from``.

    Versions are grouped per article identity ``(bwb_id, stam_id)`` and ordered by
    ``valid_from``; the last one of each identity is current (``None``). Versions
    without a ``stam_id`` have no known successor.
    """
    chains: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    result: dict[str, str | None] = {}
    for version in versions:
        if version.get("stam_id"):
            chains[(version["bwb_id"], version["stam_id"])].append(version)
        else:
            result[version["key"]] = None
    for chain in chains.values():
        chain.sort(key=lambda v: (v.get("valid_from") or "", v["key"]))
        for current, following in zip(chain, chain[1:], strict=False):
            result[current["key"]] = following.get("valid_from") or None
        result[chain[-1]["key"]] = None
    return result


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
        seen: set[str] = set()
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

                for article in toestand.articles:
                    key = self._version_key(article, bwb_id, start_date)
                    if key is None or key in seen:
                        continue
                    seen.add(key)
                    writer.add(
                        self._article_version(
                            key, article, bwb_id, start_date, toestand
                        )
                    )
                    written[bwb_id].append((key, article.stam_id))

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
                "valid_until": end_date,
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
    ) -> Node:
        props = article_version_props(article, bwb_id, toestand.citation_title)
        props.setdefault("valid_from", start_date)
        props["current"] = (
            True  # until a later version is found (finalised in build_edges)
        )
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
            self._finalise_chunk(bwb_ids, written, writer)

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
        self, bwb_ids: list[str], written: WrittenVersions, writer: EdgeWriter
    ) -> None:
        versions = list(normalize_queries.article_versions(self.store, bwb_ids))
        expected = valid_until_by_key(versions)
        self._write_valid_until(
            [
                v
                for v in versions
                if v["key"] in expected
                and (
                    v.get("valid_until") != expected[v["key"]]
                    or v.get("current") is not (expected[v["key"]] is None)
                )
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
        """An article identity that is no longer in the current toestand."""
        number, title = row.get("number"), row.get("title")
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
                "stam_id": row["stam_id"],
                "display_name": f"Artikel {number} {title or ''}".strip(),
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
                },
            }
            for v in stale
        ]
        for block in chunked(docs, 500):
            self.store.bulk_insert_or_update_nodes(COLLECTION_ARTICLE_VERSIONS, block)
