"""Normalize every historical BWB toestand into versions.

Model:

* an **Article** is one identity (BWB ``stam-id``) that keeps its identity across
  versions and renumbering;
* an **ArticleVersion** exists once per real change (``stam-id`` + ``versie-id``),
  not once per toestand — a toestand only *repeats* the versions still valid. A version
  that republishes the label, heading, place and text of the version before it (a
  republication gives every article of the Grondwet a new ``versie-id``) is no change: it is
  merged into that version, which then holds on until the next change (``merged_versions``);
* ``valid_from`` is the article's own ``inwerking`` date and ``valid_until`` is
  the ``valid_from`` of the next version of the same article (null = current),
  so "the instrument on date X" is a date query and needs no membership edges.
  Every period is half-open: ``valid_until`` is the first day the version no longer
  holds; a toestand's inclusive end date becomes the day after it;
* an identity without a ``stam-id`` (an article of a bijlage) is followed by its number, and
  it has a version per text (the XML gives it no ``versie-id``): the toestanden that repeat
  the text name one version, which begins in the first of them;
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
import hashlib
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
    EFFECT_REPUBLISHES,
    ArticleXml,
    ToestandXml,
    article_display_name,
    article_label,
    article_version_key,
    article_version_props,
    effect_kind,
    historical_article_key,
    instrument_props,
    parse_toestand,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.counting import Store
from lawgraph.db.queries.normalize import bwb as normalize_bwb
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.pipelines.normalize._bwb_places import Crumbs, Places
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

_OPEN_ENDED_DATE = "9999-12-31"
# What a toestand shows for an article before its commencement.
_PLACEHOLDER = re.compile(r"^\s*Dit onderdeel is nog niet in\s*werking getreden", re.I)
_LAPSED = re.compile(r"^\s*Vervallen\b", re.I)
EDGE_SOURCE = "bwb-history-normalize"
_INSTRUMENT_CHUNK = 200  # regulations per finalisation query
_DIGEST_CHARS = 16

WrittenVersions = dict[str, list[tuple[str, str | None]]]  # bwb_id -> [(key, stam_id)]


def _has_version_id(article: ArticleXml) -> bool:
    return bool(article.stam_id and article.versie_id)


def text_digest(text: str) -> str:
    """A short digest of an article's text: the version of an article without a versie-id."""
    return hashlib.sha1(text.encode()).hexdigest()[:_DIGEST_CHARS]


class _FirstSeen:
    """The versions of articles without a versie-id (the articles of a bijlage), each from
    the first toestand that holds its text: the toestanden come in no order, and a version
    begins in the first of them."""

    def __init__(self) -> None:
        # key -> (bwb_id, start, article, citation title, position)
        self._first: dict[str, tuple[str, str, ArticleXml, str | None, int]] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._first

    def __len__(self) -> int:
        return len(self._first)

    def keep(
        self,
        key: str,
        bwb_id: str,
        start_date: str,
        article: ArticleXml,
        toestand: ToestandXml,
        position: int,
    ) -> None:
        first = self._first.get(key)
        if first is None or start_date < first[1]:
            self._first[key] = (
                bwb_id,
                start_date,
                article,
                toestand.citation_title,
                position,
            )

    def earliest(
        self, store: Store
    ) -> dict[str, tuple[ArticleXml, str, str, str | None, int]]:
        """Per version the arguments of ``_article_version`` after the key, beginning at
        the earliest start: of this run, or of an earlier run that wrote it."""
        stored: dict[str, str] = {}
        for keys in chunked(sorted(self._first), _INSTRUMENT_CHUNK * 5):
            stored.update(normalize_bwb.article_version_starts(store, keys))
        result = {}
        for key, (bwb_id, start, article, title, position) in self._first.items():
            earlier = stored.get(key)
            if earlier and earlier < start:
                start = earlier
            result[key] = (article, bwb_id, start, title, position)
        return result


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


def content_digest(article: ArticleXml) -> str:
    """What makes two versions of an article the same: label, heading, place and text."""
    return text_digest(
        "\x1f".join(
            [
                article.label or "",
                article.heading or "",
                article.path or "",
                article.text,
            ]
        )
    )


def merged_versions(versions: Iterable[dict[str, Any]]) -> dict[str, str]:
    """The republications that repeat the version before them, each with the key of the
    first version of its run: ``{absorbed key: surviving key}``.

    *versions* are ``{key, bwb_id, stam_id, number, valid_from, effect, digest}``. Only a
    republication (effect ``tekstplaatsing-*``) is merged: an amendment the BWB records is a
    change even where the text shows none (a reference that points elsewhere now). A version
    without a digest is never merged.
    """
    chains: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for version in versions:
        chains[_identity(version)].append(version)
    absorbed: dict[str, str] = {}
    for chain in chains.values():
        chain.sort(key=lambda v: (v.get("valid_from") or "", v["key"]))
        for earlier, version in zip(chain, chain[1:], strict=False):
            if effect_kind(version.get("effect")) != EFFECT_REPUBLISHES:
                continue
            if version.get("digest") and version.get("digest") == earlier.get("digest"):
                absorbed[version["key"]] = absorbed.get(earlier["key"], earlier["key"])
    return absorbed


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
        self._incremental = False  # a run with --since: it adds to what is stored

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the raw historical toestanden (each is a large XML document)."""
        self._incremental = since is not None
        return self._iter_raw_sources(
            source=SOURCE_BWB,
            kinds=[RAW_KIND_BWB_TOESTAND_ALL],
            since=since,
            chronological=True,
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
        places = Places()
        by_text = _FirstSeen()  # the versions of articles without a versie-id

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
                self._place(places, bwb_id, start_date, toestand)

                for position, article in enumerate(toestand.articles):
                    key = self._version_key(article, bwb_id)
                    if key is None:
                        continue
                    last_seen[key] = max(last_seen.get(key, ""), start_date)
                    if not _has_version_id(article):
                        if key not in by_text:
                            written[bwb_id].append((key, article.stam_id))
                        by_text.keep(
                            key, bwb_id, start_date, article, toestand, position
                        )
                        continue
                    placeholder = is_placeholder(article.text)
                    if key in seen or (placeholder and key in announced):
                        continue
                    if key not in announced:
                        written[bwb_id].append((key, article.stam_id))
                    (announced if placeholder else seen).add(key)
                    writer.add(
                        self._article_version(
                            key,
                            article,
                            bwb_id,
                            start_date,
                            toestand.citation_title,
                            position,
                        )
                    )
            for key, first in by_text.earliest(self.store).items():
                writer.add(self._article_version(key, *first))

        logger.info(
            "Normalized %d toestanden and %d article versions for %d instruments.",
            len(instrument_versions),
            len(seen) + len(by_text),
            len(instrument_seed),
        )
        return {
            "instrument_seed": instrument_seed,
            "instrument_versions": instrument_versions,
            "written": written,
            "last_seen": last_seen,
            "places": places,
        }

    def _place(
        self, places: Places, bwb_id: str, start_date: str, toestand: ToestandXml
    ) -> None:
        """Add the versions of a toestand, in its order, to *places*; a run with --since
        first reads what an earlier run stored for the law."""
        if self._incremental and bwb_id not in places:
            places.seed(bwb_id, normalize_bwb.stored_places(self.store, bwb_id))
        versions: list[tuple[str, Crumbs]] = []
        for article in toestand.articles:
            key = self._version_key(article, bwb_id)
            if key is not None:
                versions.append((key, article.breadcrumb))
        places.add(bwb_id, start_date, versions)

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
        citation_title: str | None,
        position: int,
    ) -> Node:
        props = article_version_props(article, bwb_id, citation_title, position)
        props.setdefault("valid_from", start_date)
        props["content_digest"] = content_digest(article)
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
    def _version_key(article: ArticleXml, bwb_id: str) -> str | None:
        """Key of an article version: its ``stam-id`` and ``versie-id``; without them its
        number and its text, so every toestand that repeats the text names one version."""
        if _has_version_id(article):
            return article_version_key(
                bwb_id, str(article.stam_id), str(article.versie_id)
            )
        if article.number:
            return article_version_key(
                bwb_id, f"n{article.number}", text_digest(article.text)
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
            self._finalise_chunk(
                bwb_ids, written, normalized["last_seen"], normalized["places"], writer
            )

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
        places: Places,
        writer: EdgeWriter,
    ) -> None:
        versions = list(normalize_bwb.article_versions(self.store, bwb_ids))
        positions: dict[str, int] = {}
        for bwb_id in bwb_ids:
            positions.update(places.positions(bwb_id))
        for v in versions:
            v["last_seen"] = max(v.get("last_seen") or "", last_seen.get(v["key"], ""))
            v["lapsed"] = is_lapsed(v.get("effect"), v.get("text_start"))
        versions, raised = self._merge(versions)
        starts = normalize_bwb.toestand_starts(self.store, bwb_ids)
        expected = valid_until_by_key(versions, starts)
        self._write_valid_until(
            [
                v
                for v in versions
                if v.get("valid_until") != expected[v["key"]]
                or v.get("current") is not (expected[v["key"]] is None)
                or v["key"] in last_seen
                or v["key"] in raised
                or v.get("position") != positions.get(v["key"], v.get("position"))
            ],
            expected,
            positions,
            places,
        )
        kept = {v["key"] for v in versions}

        article_by_identity = {
            (a["bwb_id"], a["stam_id"]): a["key"]
            for a in normalize_bwb.article_identities(self.store, bwb_ids)
            if a.get("stam_id")
        }
        newest = self._newest_per_identity(versions)

        historical: list[Node] = []
        for bwb_id in bwb_ids:
            for version_key, stam_id in written.get(bwb_id, []):
                if not stam_id or version_key not in kept:
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

    def _merge(
        self, versions: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Remove the versions that repeat the version before them (with their edges); the
        surviving version is seen as long as the last of them. Returns the versions left
        and the keys of those whose ``last_seen`` went up."""
        absorbed = merged_versions(versions)
        if not absorbed:
            return versions, set()
        by_key = {v["key"]: v for v in versions}
        raised: set[str] = set()
        for key, survivor_key in absorbed.items():
            survivor = by_key[survivor_key]
            if (by_key[key]["last_seen"] or "") > (survivor["last_seen"] or ""):
                survivor["last_seen"] = by_key[key]["last_seen"]
                raised.add(survivor_key)
        normalize_edges.remove_nodes(
            self.store, COLLECTION_ARTICLE_VERSIONS, sorted(absorbed)
        )
        return [v for v in versions if v["key"] not in absorbed], raised

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
        self,
        stale: list[dict[str, Any]],
        expected: dict[str, str | None],
        positions: dict[str, int],
        places: Places,
    ) -> None:
        """Write ``valid_until`` and ``current`` of the versions where either differs, and
        the place of the versions read in this run or moved by them (``_bwb_places``).

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
                    **_place_props(v["key"], positions, places),
                },
            }
            for v in stale
        ]
        for block in chunked(docs, 500):
            self.store.bulk_insert_or_update_nodes(COLLECTION_ARTICLE_VERSIONS, block)


def _place_props(key: str, positions: dict[str, int], places: Places) -> dict[str, Any]:
    """``position`` and the breadcrumbs of a version, where this run knows them."""
    props: dict[str, Any] = places.breadcrumbs(key) or {}
    if key in positions:
        props["position"] = positions[key]
    return props
