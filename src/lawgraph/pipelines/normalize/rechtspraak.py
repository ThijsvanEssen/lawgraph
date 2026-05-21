from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    RAW_SOURCE_KINDS,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


# ── XML section-extraction helpers (module-level so their complexity is isolated) ──


def _xml_local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _xml_clean(el: ET.Element) -> str:
    return " ".join(el.itertext()).strip()


def _emit_body(child: ET.Element, paragraphs: list[dict[str, Any]]) -> None:
    text = _xml_clean(child)
    if text:
        paragraphs.append({"number": None, "kind": "body", "text": text})


def _emit_subheading(child: ET.Element, paragraphs: list[dict[str, Any]]) -> None:
    text = _xml_clean(child)
    if text:
        paragraphs.append({"number": None, "kind": "subheading", "text": text})


def _emit_generic(child: ET.Element, paragraphs: list[dict[str, Any]]) -> None:
    text = _xml_clean(child)
    if text and _xml_local(child.tag) not in ("nr",):
        paragraphs.append({"number": None, "kind": "body", "text": text})


def _process_section(
    section: ET.Element, paragraphs: list[dict[str, Any]], depth: int = 0
) -> None:
    nr = section.attrib.get("nr", "").strip() or None
    kind = "heading" if depth == 0 else "subheading"
    title_text: str | None = None
    for child in section:
        if _xml_local(child.tag) == "title":
            title_text = _xml_clean(child)
            break
    if not title_text:
        title_text = (section.text or "").strip() or None
    if title_text or nr:
        paragraphs.append({"number": nr, "kind": kind, "text": title_text or ""})
    for child in section:
        local = _xml_local(child.tag)
        if local == "title" or local == "footnote":
            pass
        elif local == "section":
            _process_section(child, paragraphs, depth=depth + 1)
        elif local in ("para", "al"):
            _emit_body(child, paragraphs)
        elif local == "uitspraak.info":
            _emit_subheading(child, paragraphs)
        else:
            _emit_generic(child, paragraphs)


def _process_uitspraak(el: ET.Element, paragraphs: list[dict[str, Any]]) -> None:
    for child in el:
        local = _xml_local(child.tag)
        if local == "section":
            _process_section(child, paragraphs, depth=0)
        elif local == "uitspraak.info":
            _emit_subheading(child, paragraphs)
        elif local in ("para", "al"):
            _emit_body(child, paragraphs)


def _extract_relation_ecli(el: ET.Element) -> str | None:
    """Return the ECLI from a dc:relation element, or None if not found."""
    ecli = (el.text or "").strip()
    if not ecli:
        for attr_name, attr_val in el.attrib.items():
            if _xml_local(attr_name) == "resource" and "id=" in attr_val:
                ecli = attr_val.split("id=")[-1].strip()
                break
    return ecli.upper() if ecli and ecli.upper().startswith("ECLI:") else None


class RechtspraakNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read Rechtspraak index and content raw_sources records."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_RECHTSPRAAK])
        rows = self._query_raw_sources(
            source=SOURCE_RECHTSPRAAK, kinds=kinds, since=since
        )
        grouped = self._group_by_kind(rows, kinds=kinds)

        index_records = grouped.get(RAW_KIND_RS_INDEX, [])
        content_records = grouped.get(RAW_KIND_RS_CONTENT, [])

        logger.info(
            "Loaded %d Rechtspraak index records and %d content records from raw_sources.",
            len(index_records),
            len(content_records),
        )

        return {"index": index_records, "content": content_records}

    @staticmethod
    def _derive_court_tier(ecli: str | None) -> tuple[str | None, str | None]:
        """Return (court_code, tier) derived from the ECLI identifier."""
        if not ecli:
            return None, None
        parts = ecli.split(":")
        court_code = parts[2].upper() if len(parts) >= 3 else None
        if court_code == "HR":
            tier: str | None = "hoge_raad"
        elif court_code and court_code.startswith("GH"):
            tier = "gerechtshof"
        elif court_code and court_code.startswith("RB"):
            tier = "rechtbank"
        else:
            tier = "bijzonder" if court_code else None
        return court_code, tier

    @staticmethod
    def _compose_display_name(props: dict[str, Any]) -> str | None:
        """Return a human-readable display name built from court, date and ECLI."""
        court = props.get("court")
        date_eff = props.get("date_eff")
        case_number = props.get("case_number")
        ecli = props.get("ecli")
        if court and date_eff and case_number:
            return f"{court} {date_eff} / {case_number}"
        if court and date_eff:
            return f"{court} {date_eff}"
        return ecli or None

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

        props: dict[str, Any] = {
            "source": SOURCE_RECHTSPRAAK,
            "ecli": ecli,
            "raw_xml": payload_text,
        }
        if raw_entry.get("kind"):
            props["source_kind"] = raw_entry["kind"]
        if meta:
            props["meta"] = meta

        summary, text = self._extract_judgment_text(payload_text)
        if summary:
            props["summary"] = summary
        if text:
            props["text"] = text

        judgment_meta, subjects = self._extract_rdf_metadata(payload_text)
        if judgment_meta:
            props["judgment_metadata"] = judgment_meta
            for field in ("court", "date", "case_number"):
                if field in judgment_meta:
                    props[field] = judgment_meta[field]
            if judgment_meta.get("related_eclis"):
                props["related_eclis"] = judgment_meta["related_eclis"]
        if subjects:
            props["subjects"] = subjects

        sections = self._extract_sections(payload_text)
        if sections:
            props["paragraphs"] = sections

        court_code, tier = self._derive_court_tier(ecli)
        props["court_code"] = court_code
        props["tier"] = tier
        jm_date = judgment_meta.get("date") if isinstance(judgment_meta, dict) else None
        props["date_eff"] = (
            jm_date or (meta.get("date") if meta else None) or props.get("date")
        )
        props["display_name"] = self._compose_display_name(props)
        node = Node(
            collection=COLLECTION_JUDGMENTS,
            type=NodeType.JUDGMENT,
            key=make_node_key(ecli),
            labels=["Rechtspraak"],
            props=props,
        )
        return ecli, node

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Convert Rechtspraak content payloads into judgment nodes."""
        judgments_by_ecli: dict[str, Node] = {}
        for raw_entry in raw.get("content", []):
            ecli, node = self._build_content_node(raw_entry)
            if ecli and node:
                judgments_by_ecli[ecli] = self.store.insert_or_update(node)

        logger.info("Created %d Rechtspraak judgment nodes.", len(judgments_by_ecli))

        # Create lightweight ECLI stub nodes from index records.
        index_records = raw.get("index", [])

        # Collect candidate (ecli, key) pairs, skipping ECLIs already written as
        # full content nodes in this same run (those are definitely not stubs).
        stub_candidates: list[tuple[str, str]] = []
        for raw_entry in index_records:
            meta = self._meta(raw_entry)
            ecli = meta.get("ecli")
            if not ecli:
                continue
            if ecli in judgments_by_ecli:
                continue
            stub_candidates.append((ecli, make_node_key(ecli)))

        # Bulk-fetch keys of existing non-stub nodes so we don't overwrite them.
        non_stub_keys: set[str] = set()
        if stub_candidates:
            candidate_keys = [key for _ecli, key in stub_candidates]
            aql = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
  FILTER doc._key IN @keys AND (doc.props.stub == null OR doc.props.stub == false)
  RETURN doc._key
"""
            non_stub_keys = cast(
                set[str], set(self.store.query(aql, {"keys": candidate_keys}))
            )

        # Build and batch-upsert stub documents.
        stub_docs: list[dict] = []
        for ecli, key in stub_candidates:
            if key in non_stub_keys:
                continue
            stub_node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=key,
                labels=["Rechtspraak", "Stub"],
                props={
                    "source": SOURCE_RECHTSPRAAK,
                    "ecli": ecli,
                    "stub": True,
                    "display_name": ecli,
                },
            )
            stub_docs.append(stub_node.to_document())

        stubs_created = 0
        for batch_start in range(0, len(stub_docs), 200):
            batch = stub_docs[batch_start : batch_start + 200]
            created, updated = self.store.bulk_insert_or_update_nodes(
                COLLECTION_JUDGMENTS, batch
            )
            stubs_created += created + updated

        logger.info(
            "Created/updated %d Rechtspraak ECLI stub nodes from index records.",
            stubs_created,
        )

        return {
            "judgments_by_ecli": judgments_by_ecli,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """No structural edges to build for Rechtspraak judgments."""
        return 0

    @staticmethod
    def _extract_judgment_text(
        payload_text: str | None,
    ) -> tuple[str | None, str | None]:
        """Return (summary, full_text) extracted from Rechtspraak XML."""
        if not payload_text:
            return None, None
        try:
            root = ET.fromstring(payload_text)
        except ET.ParseError:
            return None, None

        def _itertext(el: ET.Element) -> str:
            return " ".join(el.itertext()).strip()

        summary: str | None = None
        for el in root.iter():
            if _xml_local(el.tag) == "inhoudsindicatie":
                text = _itertext(el)
                if text:
                    summary = text
                break

        full_text: str | None = None
        parts: list[str] = []
        for el in root.iter():
            if _xml_local(el.tag) == "uitspraak":
                parts.append(_itertext(el))
        if parts:
            full_text = "\n\n".join(p for p in parts if p) or None

        return summary, full_text

    @staticmethod
    def _extract_rdf_metadata(
        payload_text: str | None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Return (judgment_metadata, subjects) from <rdf:Description>."""
        if not payload_text:
            return {}, []
        try:
            root = ET.fromstring(payload_text)
        except ET.ParseError:
            return {}, []

        meta: dict[str, Any] = {}
        subjects: list[str] = []
        related_eclis: list[str] = []

        for el in root.iter():
            tag = _xml_local(el.tag)
            text = (el.text or "").strip()

            if tag == "relation":
                ecli = _extract_relation_ecli(el)
                if ecli:
                    related_eclis.append(ecli)
                continue

            if not text:
                continue
            if tag == "creator" and "court" not in meta:
                meta["court"] = text
            elif tag == "date" and "date" not in meta:
                meta["date"] = text
            elif tag == "zaaknummer" and "case_number" not in meta:
                meta["case_number"] = text
            elif tag == "procedure" and "type" not in meta:
                meta["type"] = text
            elif tag == "subject":
                subjects.append(text)

        if related_eclis:
            meta["related_eclis"] = related_eclis

        return meta, subjects

    @staticmethod
    def _extract_sections(
        payload_text: str | None,
    ) -> list[dict[str, Any]]:
        """Return one entry per semantic unit (heading / subheading / body) in <uitspraak>.

        Each section becomes a heading entry, each <title>/<uitspraak.info> becomes a
        subheading, and each <para>/<al> becomes a body entry.
        """
        if not payload_text:
            return []
        try:
            root = ET.fromstring(payload_text)
        except ET.ParseError:
            return []

        paragraphs: list[dict[str, Any]] = []
        for el in root.iter():
            if _xml_local(el.tag) == "uitspraak":
                _process_uitspraak(el, paragraphs)
                break
        return paragraphs
