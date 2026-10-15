"""Normalize pipeline for ECHR HUDOC judgments: a node per judgment, with its text."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
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
from lawgraph.core.echr_findings import echr_outcome_props
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json, payload_text
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


# The language of the record that becomes the judgment, best first.
_LANGUAGES = ("ENG", "FRE")


def _language_rank(language: str | None) -> int:
    return _LANGUAGES.index(language) if language in _LANGUAGES else len(_LANGUAGES)


def _judgment(ecli: str | None, item_id: str, props: dict[str, Any]) -> Node:
    """The judgment node: keyed by its ECLI, else by its HUDOC item id."""
    return Node(
        collection=COLLECTION_JUDGMENTS,
        key=make_node_key(ecli) if ecli else make_node_key("echr", item_id),
        labels=["ECHR"],
        props=props,
    )


class ECHRNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalize ECHR HUDOC judgment JSON into Judgment nodes."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_ECHR,
            kinds=[RAW_KIND_ECHR_JUDGMENT, RAW_KIND_ECHR_TEXT],
            since=since,
            # a text is up to a megabyte of XML
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The judgments and their texts. No edges: citations are linked by the semantic
        pipelines."""
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
                continue
            writer.add(node)
            count += 1
        judgments.flush()
        texts.flush()

        logger.info("ECHR normalize: %d judgments and texts processed.", count)

    def _judgment_node(
        self, record: dict[str, Any], best_language: dict[str, int]
    ) -> Node | None:
        """The judgment of a HUDOC record; None for a record without an item id, and for a
        translation of a judgment whose record in a better language was seen already."""
        payload = payload_json(record)
        if not payload:
            self.progress.skip("no payload", record.get("external_id"))
            return None
        item_id = str(payload.get("itemid") or record.get("external_id") or "")
        if not item_id:
            self.progress.skip("no item id", record.get("key"))
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
            # what it found per article, and whether it found a violation
            **echr_outcome_props(payload.get("conclusion")),
            # of the record: a decision is in HUDOC once per language (``echr-versions``)
            "language": payload.get("languageisocode") or None,
        }
        # HUDOC gives 1 (a key case) to 4, as a string
        importance = str(payload.get("importance") or "")
        if importance.isdigit():
            props["importance"] = int(importance)
        elif importance:
            self.progress.problem("importance not a number", f"{item_id}: {importance}")

        # By its ECLI when it has one: that is what a Dutch judgment cites, so the stub
        # of a cited judgment and the judgment itself are the same node. HUDOC holds a
        # judgment once per language; the English record is the one that stays, else the
        # French one, the languages whose text is fetched.
        ecli = str(payload.get("ecli") or "").strip().upper()
        if ecli:
            props["ecli"] = ecli
            rank = _language_rank(payload.get("languageisocode"))
            if best_language.get(ecli, rank) < rank:
                self.progress.skip("a translation; a better language is kept", item_id)
                return None
            best_language[ecli] = rank
        return _judgment(ecli or None, item_id, props)

    def _text_node(self, record: dict[str, Any]) -> Node | None:
        """The text and paragraphs of a judgment, from the DOCX body HUDOC serves."""
        item_id = str(record.get("external_id") or "")
        xml_text = payload_text(record)
        if not item_id or not xml_text:
            self.progress.skip("no text", item_id or record.get("key"))
            return None
        try:
            text, paragraphs = read_judgment(xml_text)
        except ValueError as exc:
            self.progress.fail("text not readable", f"{item_id}: {exc}")
            return None
        ecli = str((record.get("meta") or {}).get("ecli") or "").upper() or None
        props: dict[str, Any] = {"source": SOURCE_ECHR, "text": text}
        if paragraphs:
            props["paragraphs"] = paragraphs
        if ecli:
            props["ecli"] = ecli
        return _judgment(ecli, item_id, props)
