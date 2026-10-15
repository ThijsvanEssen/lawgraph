from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.case_numbers import case_number_keys, translated_case_number
from lawgraph.core.decision_kinds import KIND_CONCLUSIE, decision_kind
from lawgraph.core.judgment_advocate_general import (
    advocate_general,
    advocate_general_role,
)
from lawgraph.core.judgment_counsel import read_counsel
from lawgraph.core.judgment_metadata import (
    compose_display_name,
    derive_court,
    extract_judgment_text,
    extract_rdf_metadata,
    is_english,
    parse_judgment,
    published_on,
    replacing_ecli,
)
from lawgraph.core.judgment_names import judgment_names
from lawgraph.core.judgment_outcome import outcome_props
from lawgraph.core.judgment_paragraphs import judgment_text, kop_lines
from lawgraph.core.judgment_parties import read_parties
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries.normalize import rechtspraak as normalize_rechtspraak
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

RAW_BATCH_SIZE = 200


def _metadata_props(root: ET.Element) -> dict[str, Any]:
    """What the RDF metadata of a judgment says: ``judgment_metadata``, with the court, the
    date, the case number, the replacing and related ECLIs and the case numbers as compared
    lifted out of it, and the ``subjects``."""
    judgment_meta, subjects = extract_rdf_metadata(root)
    props: dict[str, Any] = {}
    if judgment_meta:
        props["judgment_metadata"] = judgment_meta
        for field in ("court", "date", "case_number"):
            if field in judgment_meta:
                props[field] = judgment_meta[field]
        props["replaced_by"] = replacing_ecli(judgment_meta.get("replaced_by"))
        for field in ("related_eclis", "later_eclis", "conclusion_eclis"):
            if judgment_meta.get(field):
                props[field] = judgment_meta[field]
        if keys := case_number_keys(judgment_meta.get("case_number")):
            props["case_number_keys"] = keys
    if subjects:
        props["subjects"] = subjects
    return props


def _text_props(
    root: ET.Element, kop: list[str], subjects: list[str]
) -> dict[str, Any]:
    """The ``paragraphs`` and ``footnotes`` of a judgment, and the ``parties`` its kop and
    paragraphs name."""
    paragraphs, footnotes = judgment_text(root)
    props: dict[str, Any] = {"paragraphs": paragraphs} if paragraphs else {}
    # what a court cites in a footnote (``semantic rechtspraak`` reads it too)
    props["footnotes"] = footnotes or None
    props["parties"] = read_counsel(read_parties(kop, subjects), paragraphs, subjects)
    return props


def _court_props(ecli: str, court: str | None) -> dict[str, Any]:
    """The ``court_code``, ``tier`` and ``court_kind`` of a judgment, from its ECLI and the
    court its metadata names."""
    court_code, tier, court_kind = derive_court(ecli, court)
    return {"court_code": court_code, "tier": tier, "court_kind": court_kind}


def _decision_props(
    props: dict[str, Any], root: ET.Element, kop: list[str]
) -> dict[str, Any]:
    """The ``decision_kind`` of a judgment with the props read so far (``_metadata_props``,
    ``_text_props``, ``_court_props``), the advocate-general of a conclusion, and how it
    ended."""
    judgment_meta = props.get("judgment_metadata", {})
    kind = decision_kind(
        document_type=judgment_meta.get("document_type"),
        procedure=judgment_meta.get("type"),
        kop=kop,
        court_kind=props["court_kind"],
        subjects=props.get("subjects", []),
    )
    decision: dict[str, Any] = {"decision_kind": kind}
    if kind == KIND_CONCLUSIE:
        decision["advocate_general"] = advocate_general(root)
        decision["advocate_general_role"] = advocate_general_role(props.get("text"))
    decision.update(outcome_props(kind, props.get("paragraphs", [])))
    return decision


class RechtspraakNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(
        self, *, store: GraphStore, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that record key, so many
        judgments; the log names the last one read."""
        super().__init__(store=store)
        self.after = after
        self.limit = limit
        self.last_record_read: str | None = None
        # the translations written, linked to what they translate once all are written
        self._translations: list[dict[str, Any]] = []

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = super().run(since=since)
        if self.after or self.limit is not None:
            last = self.last_record_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """The Rechtspraak content raw_sources records (of the slice), streamed in small
        batches, the key of each kept as the last read.

        A judgment is tens of KB of XML and a run holds tens of thousands: the records are
        read as they are normalized, not loaded first.
        """
        for record in self._iter_raw_sources(
            source=SOURCE_RECHTSPRAAK,
            kinds=[RAW_KIND_RS_CONTENT],
            since=since,
            batch_size=RAW_BATCH_SIZE,
            after=self.after,
            limit=self.limit,
        ):
            self.last_record_read = record.get("_key") or self.last_record_read
            yield record

    def _build_content_node(self, raw_entry: dict[str, Any]) -> Node | None:
        """The judgment node of one content raw_sources record; None for a record without
        an ECLI or with XML that cannot be read."""
        meta = self._meta(raw_entry)
        ecli = meta.get("ecli")
        if not ecli:
            self.progress.skip("no ECLI", raw_entry.get("_key"))
            return None
        try:
            root = parse_judgment(self._payload_text(raw_entry))  # once, for all below
        except ValueError as exc:
            # ``retrieve rechtspraak --ecli`` fetches it again
            self.progress.fail("unreadable judgment XML", f"{ecli}: {exc}")
            return None

        props: dict[str, Any] = {"source": SOURCE_RECHTSPRAAK, "ecli": ecli}
        if raw_entry.get("kind"):
            props["source_kind"] = raw_entry["kind"]
        props["meta"] = meta
        summary, text = extract_judgment_text(root)
        self._set_summary(props, summary)
        if text:
            props["text"] = text
        kop = kop_lines(root)
        props.update(_metadata_props(root))
        props.update(_text_props(root, kop, props.get("subjects", [])))
        props.update(_court_props(ecli, props.get("court")))
        props.update(_decision_props(props, root, kop))
        props["names"] = judgment_names(ecli)
        props["date_eff"] = props.get("date") or meta.get("date")
        props["published_on"] = published_on(root)
        props["display_name"] = compose_display_name(props)
        key = make_node_key(ecli)
        self._remember_translation(key, props)
        return Node(
            collection=COLLECTION_JUDGMENTS,
            key=key,
            labels=["Rechtspraak"],
            props=props,
        )

    @staticmethod
    def _set_summary(props: dict[str, Any], summary: str | None) -> None:
        """The inhoudsindicatie as ``summary``; an English one (a translation) as
        ``summary_en``, ``summary`` then that of the judgment it translates
        (``_link_translations``)."""
        if summary and is_english(summary):
            props["summary_en"] = summary
        else:
            # null clears what an earlier run stored ("kopje volgt", now a placeholder)
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

    def _link_translations(self) -> None:
        """Give each translation of this run the Dutch summary of the judgment it translates
        (same court, day and case number) and that judgment its English summary."""
        if not self._translations:
            return
        lookup = [
            {k: row[k] for k in ("key", "court_code", "date", "case_key")}
            for row in self._translations
        ]
        originals = {
            found["key"]: found["original"]
            for found in normalize_rechtspraak.translated_judgments(self.store, lookup)
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
        normalize_rechtspraak.update_judgment_props(self.store, updates)
        logger.info(
            "Linked %d of %d English translation(s) to the judgment they translate.",
            len(originals),
            len(self._translations),
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """Convert Rechtspraak content payloads into judgment nodes, one batch at a time.
        No structural edges."""
        count = 0
        with NodeWriter(self.store) as writer:
            for raw_entry in raw:
                if node := self._build_content_node(raw_entry):
                    writer.add(node)
                    count += 1
        self._link_translations()
        logger.info("Created %d Rechtspraak judgment nodes.", count)
