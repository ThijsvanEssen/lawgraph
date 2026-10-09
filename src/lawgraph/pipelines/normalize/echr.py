"""Normalize pipeline for ECHR HUDOC judgments: a node per judgment, with its text."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    MAX_TITLE_CHARS,
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_ECHR_TEXT,
    SOURCE_ECHR,
)
from lawgraph.core.display import shorten
from lawgraph.core.echr_docx import read_judgment
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db import NodeWriter
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


# The language of the record that becomes the judgment, best first.
_LANGUAGES = ("ENG", "FRE")


def _language_rank(language: str | None) -> int:
    return _LANGUAGES.index(language) if language in _LANGUAGES else len(_LANGUAGES)


def _judgment(ecli: str | None, item_id: str, props: dict[str, Any]) -> Node:
    """The judgment node: keyed by its ECLI, else by its HUDOC item id."""
    return Node(
        collection=COLLECTION_JUDGMENTS,
        type=NodeType.JUDGMENT,
        key=make_node_key(ecli) if ecli else make_node_key("echr", item_id),
        labels=["ECHR"],
        props=props,
    )


class ECHRNormalizePipeline(NormalizePipelineBase):
    """Normalize ECHR HUDOC judgment JSON into Judgment nodes."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_ECHR,
            kinds=[RAW_KIND_ECHR_JUDGMENT, RAW_KIND_ECHR_TEXT],
            since=since,
            # a text is up to a megabyte of XML
            batch_size=20,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        count = 0
        best_language: dict[str, int] = {}
        # Two writers: a writer keeps the last node of a key in its buffer, and a judgment
        # and its text are two nodes of one key, merged by the upserts.
        judgments, texts = NodeWriter(self.store), NodeWriter(self.store)
        for record in raw:
            if record.get("kind") == RAW_KIND_ECHR_TEXT:
                node, writer = self._text_node(record), texts
            else:
                node, writer = self._judgment_node(record, best_language), judgments
            if node is None:
                result.skipped += 1
                continue
            writer.add(node)
            count += 1
        judgments.flush()
        texts.flush()

        logger.info("ECHR normalize: %d judgments and texts processed.", count)
        return count

    def _judgment_node(
        self, record: dict[str, Any], best_language: dict[str, int]
    ) -> Node | None:
        """The judgment of a HUDOC record; None for a record without an item id, and for a
        translation of a judgment whose record in a better language was seen already."""
        payload = self._payload_json(record)
        if not payload or not isinstance(payload, dict):
            return None
        item_id = str(payload.get("itemid") or record.get("external_id") or "")
        if not item_id:
            return None

        appno = payload.get("appno") or ""
        docname = payload.get("docname") or f"ECHR {item_id}"
        articles = payload.get("article") or []
        props: dict[str, Any] = {
            "source": SOURCE_ECHR,
            "external_id": item_id,
            "appno": appno,
            "title": docname,
            "display_name": shorten(docname, MAX_TITLE_CHARS),
            "date": _iso_date(payload.get("kpdate")),
            "respondent": payload.get("respondent") or "",
            "originating_body": payload.get("originatingbody") or "",
            "articles": articles if isinstance(articles, list) else [articles],
            "conclusion": payload.get("conclusion") or "",
            # of the record: a decision is in HUDOC once per language (``echr-versions``)
            "language": payload.get("languageisocode") or None,
        }
        importance = payload.get("importance")
        if importance is not None:
            try:
                props["importance"] = int(importance)
            except (TypeError, ValueError):
                props["importance"] = importance

        # By its ECLI when it has one: that is what a Dutch judgment cites, so the stub
        # of a cited judgment and the judgment itself are the same node. HUDOC holds a
        # judgment once per language; the English record is the one that stays, else the
        # French one, the languages whose text is fetched.
        ecli = str(payload.get("ecli") or "").strip().upper()
        if ecli:
            props["ecli"] = ecli
            rank = _language_rank(payload.get("languageisocode"))
            if best_language.get(ecli, rank) < rank:
                return None
            best_language[ecli] = rank
        return _judgment(ecli or None, item_id, props)

    def _text_node(self, record: dict[str, Any]) -> Node | None:
        """The text and paragraphs of a judgment, from the DOCX body HUDOC serves."""
        item_id = str(record.get("external_id") or "")
        xml_text = self._payload_text(record)
        if not item_id or not xml_text:
            return None
        try:
            text, paragraphs = read_judgment(xml_text)
        except ValueError as exc:
            logger.warning("ECHR text %s cannot be read: %s", item_id, exc)
            return None
        ecli = str((record.get("meta") or {}).get("ecli") or "").upper() or None
        props: dict[str, Any] = {"source": SOURCE_ECHR, "text": text}
        if paragraphs:
            props["paragraphs"] = paragraphs
        if ecli:
            props["ecli"] = ecli
        return _judgment(ecli, item_id, props)

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """No structural edges: citations are linked by the semantic pipelines."""
