"""Pure parsing/deriving helpers for Rechtspraak judgments (no I/O, no store)."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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


def parse_judgment(payload_text: str | None) -> ET.Element:
    """The root of a judgment XML; ``ValueError`` when *payload_text* is not XML.

    Parsed once by the caller and handed to the extractors below: a judgment that cannot
    be read must not become a judgment without court, date and text.
    """
    try:
        return ET.fromstring(payload_text or "")
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc


def extract_judgment_text(root: ET.Element) -> tuple[str | None, str | None]:
    """Return ``(summary, full_text)`` of a parsed judgment."""
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


def extract_rdf_metadata(root: ET.Element) -> tuple[dict[str, Any], list[str]]:
    """Return ``(judgment_metadata, subjects)`` from ``<rdf:Description>``."""
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


def extract_sections(root: ET.Element) -> list[dict[str, Any]]:
    """One entry per semantic unit (heading / subheading / body) in ``<uitspraak>``.

    Each section becomes a heading entry, each ``<title>``/``<uitspraak.info>`` a
    subheading, and each ``<para>``/``<al>`` a body entry. Only the first
    ``<uitspraak>`` is read.
    """
    paragraphs: list[dict[str, Any]] = []
    uitspraak = first_named(root, "uitspraak")
    if uitspraak is not None:
        _process_uitspraak(uitspraak, paragraphs)
    return paragraphs


# ── Atom index pages ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IndexEntry:
    """One judgment of a Rechtspraak index page."""

    ecli: str
    updated: dt.datetime | None  # when the judgment was published or last changed
    title: str


def parse_index(xml_text: str) -> tuple[int | None, list[IndexEntry]]:
    """``(total, entries)`` of an Atom index page; the total is what the search matched.

    Raises on a page that is not XML (``ET.ParseError``) or not a feed (``ValueError``; a
    maintenance page can be well-formed): an index that cannot be read must not look like
    an empty one.
    """
    root = ET.fromstring(xml_text)
    if local_name(root.tag) != "feed":
        raise ValueError(f"not an Atom feed: the page is a <{local_name(root.tag)}>")
    total: int | None = None
    entries: list[IndexEntry] = []
    for child in root:
        name = local_name(child.tag)
        if name == "subtitle":
            match = re.search(r"(\d+)", child.text or "")
            total = int(match.group(1)) if match else None
        elif name == "entry":
            fields = {local_name(e.tag): (e.text or "").strip() for e in child}
            if fields.get("id"):
                entries.append(
                    IndexEntry(
                        ecli=fields["id"],
                        updated=_parse_timestamp(fields.get("updated")),
                        title=fields.get("title", ""),
                    )
                )
    return total, entries


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
