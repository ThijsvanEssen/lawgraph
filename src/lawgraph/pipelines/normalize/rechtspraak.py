from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.judgment_names import judgment_names
from lawgraph.core.judgment_parties import read_parties
from lawgraph.core.judgments import (
    case_number_keys,
    compose_display_name,
    decision_kind,
    derive_court_tier,
    extract_judgment_text,
    extract_rdf_metadata,
    extract_sections,
    is_english,
    kop_lines,
    parse_judgment,
    translated_case_number,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, NodeWriter
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

RAW_BATCH_SIZE = 200


class RechtspraakNormalizePipeline(NormalizePipelineBase):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, Iterator[dict[str, Any]]]:
        """The Rechtspraak content raw_sources records, streamed in small batches.

        A judgment is tens of KB of XML and a run holds tens of thousands: the records are
        read as they are normalized, not loaded first.
        """
        return {
            "content": self._iter_raw_sources(
                source=SOURCE_RECHTSPRAAK,
                kinds=[RAW_KIND_RS_CONTENT],
                since=since,
                batch_size=RAW_BATCH_SIZE,
            )
        }

    def _build_content_node(
        self, raw_entry: dict[str, Any]
    ) -> tuple[str | None, Node | None]:
        """Process one content raw_sources entry; return (ecli, Node) or (None, None)."""
        payload_text = self._payload_text(raw_entry)
        meta = self._meta(raw_entry)
        ecli = meta.get("ecli")
        if not ecli:
            logger.warning(
                "Skipping Rechtspraak content record without ECLI (_key=%s).",
                raw_entry.get("_key"),
            )
            return None, None

        try:
            root = parse_judgment(payload_text)  # once, for the extractors below
        except ValueError as exc:
            self._unreadable.append(f"{ecli} ({exc})")
            return None, None

        props: dict[str, Any] = {
            "source": SOURCE_RECHTSPRAAK,
            "ecli": ecli,
        }
        if raw_entry.get("kind"):
            props["source_kind"] = raw_entry["kind"]
        if meta:
            props["meta"] = meta

        summary, text = extract_judgment_text(root)
        self._set_summary(props, summary)
        if text:
            props["text"] = text

        judgment_meta, subjects = extract_rdf_metadata(root)
        if judgment_meta:
            props["judgment_metadata"] = judgment_meta
            for field in ("court", "date", "case_number"):
                if field in judgment_meta:
                    props[field] = judgment_meta[field]
            for field in ("related_eclis", "conclusion_eclis"):
                if judgment_meta.get(field):
                    props[field] = judgment_meta[field]
            if keys := case_number_keys(judgment_meta.get("case_number")):
                props["case_number_keys"] = keys
        if subjects:
            props["subjects"] = subjects

        sections = extract_sections(root)
        if sections:
            props["paragraphs"] = sections
        kop = kop_lines(root)
        props["parties"] = read_parties(kop, subjects)

        court_code, tier = derive_court_tier(ecli, props.get("court"))
        props["court_code"] = court_code
        props["tier"] = tier
        props["decision_kind"] = decision_kind(
            document_type=judgment_meta.get("document_type"),
            procedure=judgment_meta.get("type"),
            kop=kop,
            tier=tier,
            subjects=subjects,
        )
        props["names"] = judgment_names(ecli)
        jm_date = judgment_meta.get("date") if isinstance(judgment_meta, dict) else None
        props["date_eff"] = (
            jm_date or (meta.get("date") if meta else None) or props.get("date")
        )
        props["display_name"] = compose_display_name(props)
        key = make_node_key(ecli)
        node = Node(
            collection=COLLECTION_JUDGMENTS,
            type=NodeType.JUDGMENT,
            key=key,
            labels=["Rechtspraak"],
            props=props,
        )
        self._remember_translation(key, props)
        return ecli, node

    @staticmethod
    def _set_summary(props: dict[str, Any], summary: str | None) -> None:
        """The inhoudsindicatie as ``summary``; an English one (a translation) as
        ``summary_en``, ``summary`` then that of the judgment it translates
        (``_link_translations``)."""
        if summary and is_english(summary):
            props["summary_en"] = summary
        elif summary:
            props["summary"] = summary

    def _remember_translation(self, key: str, props: dict[str, Any]) -> None:
        """Note a translation, to link to the judgment it translates once all are written."""
        original_number = translated_case_number(props.get("case_number"))
        case_keys = case_number_keys(original_number)
        if props.get("summary_en") and case_keys:
            self._translations.append(
                {
                    "key": key,
                    "court_code": props.get("court_code"),
                    "date": props.get("date_eff"),
                    "case_key": case_keys[0],
                    "summary_en": props["summary_en"],
                }
            )

    def _link_translations(self) -> int:
        """Give each translation of this run the Dutch summary of the judgment it translates
        (same court, day and case number) and that judgment its English summary."""
        if not self._translations:
            return 0
        lookup = [
            {k: row[k] for k in ("key", "court_code", "date", "case_key")}
            for row in self._translations
        ]
        originals = {
            found["key"]: found["original"]
            for found in normalize_queries.translated_judgments(self.store, lookup)
        }
        updates: list[dict[str, Any]] = []
        for row in self._translations:
            original = originals.get(row["key"]) or {}
            # without the judgment it translates, no summary (not an English one)
            updates.append(
                {
                    "key": row["key"],
                    "props": {
                        "summary": original.get("summary"),
                        "translation_of": original.get("ecli"),
                    },
                }
            )
            if original:
                updates.append(
                    {"key": original["key"], "props": {"summary_en": row["summary_en"]}}
                )
        linked = len(originals)
        normalize_queries.update_judgment_props(self.store, updates)
        logger.info(
            "Linked %d of %d English translation(s) to the judgment they translate.",
            linked,
            len(self._translations),
        )
        return linked

    def normalize_nodes(
        self,
        raw: dict[str, Iterator[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Convert Rechtspraak content payloads into judgment nodes, one batch at a time."""
        count = 0
        self._unreadable: list[str] = []
        self._translations: list[dict[str, Any]] = []
        with NodeWriter(self.store) as writer:
            for raw_entry in raw.get("content", []):
                ecli, node = self._build_content_node(raw_entry)
                if ecli and node:
                    writer.add(node)
                    count += 1
                else:
                    result.skipped += 1
        self._link_translations()

        if self._unreadable:
            logger.warning(
                "%d judgment(s) whose stored XML cannot be read were left out (first: %s); "
                "`retrieve rechtspraak --ecli` fetches one again.",
                len(self._unreadable),
                self._unreadable[0],
            )
        logger.info("Created %d Rechtspraak judgment nodes.", count)
        return {"judgments": count}

    def build_edges(
        self,
        raw: dict[str, Iterator[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> None:
        """No structural edges to build for Rechtspraak judgments."""
