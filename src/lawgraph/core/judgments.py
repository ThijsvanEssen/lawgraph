"""Pure parsing/deriving helpers for Rechtspraak judgments (no I/O, no store)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.xml import first_named, iter_named, local_name, text_of

# ── ECLI-derived attributes ──────────────────────────────────────────────────

TIER_HOGE_RAAD = "hoge_raad"
TIER_GERECHTSHOF = "gerechtshof"
TIER_RECHTBANK = "rechtbank"
TIER_BIJZONDER = "bijzonder"


def derive_court_tier(ecli: str | None) -> tuple[str | None, str | None]:
    """Return ``(court_code, tier)`` derived from the ECLI identifier."""
    if not ecli:
        return None, None
    parts = ecli.split(":")
    court_code = parts[2].upper() if len(parts) >= 3 else None
    if court_code == "HR":
        tier: str | None = TIER_HOGE_RAAD
    elif court_code and court_code.startswith("GH"):
        tier = TIER_GERECHTSHOF
    elif court_code and court_code.startswith("RB"):
        tier = TIER_RECHTBANK
    else:
        tier = TIER_BIJZONDER if court_code else None
    return court_code, tier


def compose_display_name(props: dict[str, Any]) -> str | None:
    """Human-readable display name built from court, date and ECLI."""
    court = props.get("court")
    date_eff = props.get("date_eff")
    case_number = props.get("case_number")
    if court and date_eff and case_number:
        return f"{court} {date_eff} / {case_number}"
    if court and date_eff:
        return f"{court} {date_eff}"
    return props.get("ecli") or None


# ── judgment XML ─────────────────────────────────────────────────────────────


def _parse(payload_text: str | None) -> ET.Element | None:
    """Parse *payload_text*; ``None`` for empty or malformed XML."""
    if not payload_text:
        return None
    try:
        return ET.fromstring(payload_text)
    except ET.ParseError:
        return None


def extract_judgment_text(
    payload_text: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(summary, full_text)`` extracted from Rechtspraak XML."""
    root = _parse(payload_text)
    if root is None:
        return None, None

    summary = text_of(first_named(root, "inhoudsindicatie"), " ") or None
    parts = [text_of(el, " ") for el in iter_named(root, "uitspraak")]
    full_text = "\n\n".join(p for p in parts if p) or None
    return summary, full_text


def relation_ecli(element: ET.Element) -> str | None:
    """ECLI from a ``dc:relation`` element (text or ``rdf:resource``), else ``None``."""
    ecli = (element.text or "").strip()
    if not ecli:
        for attr_name, attr_val in element.attrib.items():
            if local_name(attr_name) == "resource" and "id=" in attr_val:
                ecli = attr_val.split("id=")[-1].strip()
                break
    return ecli.upper() if ecli and ecli.upper().startswith("ECLI:") else None


# dc:/psi: element -> judgment_metadata field; the first non-empty one wins.
_METADATA_FIELDS = {
    "creator": "court",
    "date": "date",
    "zaaknummer": "case_number",
    "procedure": "type",
}


def extract_rdf_metadata(
    payload_text: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``(judgment_metadata, subjects)`` from ``<rdf:Description>``."""
    root = _parse(payload_text)
    if root is None:
        return {}, []

    meta: dict[str, Any] = {}
    subjects: list[str] = []
    related_eclis: list[str] = []

    for el in root.iter():
        tag = local_name(el.tag)
        if tag == "relation":
            ecli = relation_ecli(el)
            if ecli:
                related_eclis.append(ecli)
            continue

        text = (el.text or "").strip()
        if not text:
            continue
        field = _METADATA_FIELDS.get(tag)
        if field is not None:
            meta.setdefault(field, text)
        elif tag == "subject":
            subjects.append(text)

    if related_eclis:
        meta["related_eclis"] = related_eclis
    return meta, subjects


# ── <uitspraak> structure ────────────────────────────────────────────────────


def _emit(paragraphs: list[dict[str, Any]], kind: str, text: str) -> None:
    if text:
        paragraphs.append({"number": None, "kind": kind, "text": text})


def _process_section(
    section: ET.Element, paragraphs: list[dict[str, Any]], depth: int = 0
) -> None:
    nr = section.attrib.get("nr", "").strip() or None
    kind = "heading" if depth == 0 else "subheading"
    title_text: str | None = None
    for child in section:
        if local_name(child.tag) == "title":
            title_text = text_of(child, " ")
            break
    if not title_text:
        title_text = (section.text or "").strip() or None
    if title_text or nr:
        paragraphs.append({"number": nr, "kind": kind, "text": title_text or ""})
    for child in section:
        local = local_name(child.tag)
        if local in ("title", "footnote"):
            continue
        if local == "section":
            _process_section(child, paragraphs, depth=depth + 1)
        elif local == "uitspraak.info":
            _emit(paragraphs, "subheading", text_of(child, " "))
        elif local != "nr":  # para, al and any other element are body text
            _emit(paragraphs, "body", text_of(child, " "))


def _process_uitspraak(element: ET.Element, paragraphs: list[dict[str, Any]]) -> None:
    for child in element:
        local = local_name(child.tag)
        if local == "section":
            _process_section(child, paragraphs, depth=0)
        elif local == "uitspraak.info":
            _emit(paragraphs, "subheading", text_of(child, " "))
        elif local in ("para", "al"):
            _emit(paragraphs, "body", text_of(child, " "))


def extract_sections(payload_text: str | None) -> list[dict[str, Any]]:
    """One entry per semantic unit (heading / subheading / body) in ``<uitspraak>``.

    Each section becomes a heading entry, each ``<title>``/``<uitspraak.info>`` a
    subheading, and each ``<para>``/``<al>`` a body entry. Only the first
    ``<uitspraak>`` is read.
    """
    root = _parse(payload_text)
    paragraphs: list[dict[str, Any]] = []
    uitspraak = first_named(root, "uitspraak") if root is not None else None
    if uitspraak is not None:
        _process_uitspraak(uitspraak, paragraphs)
    return paragraphs


# ── Atom index pages ─────────────────────────────────────────────────────────


def count_index_entries(xml_text: str) -> int:
    """Count the Atom ``<entry>`` children of an index page (substring count if malformed)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text.count("<entry>")
    return sum(1 for child in root if local_name(child.tag) == "entry")
