"""Pure parsing/deriving helpers for Rechtspraak judgments (no I/O, no store)."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from lawgraph.core.xml import (
    collapse_ws,
    first_named,
    iter_named,
    local_name,
    text_of,
)

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
    """ECLI from a ``dcterms:relation`` element, else ``None``: its
    ``ecli:resourceIdentifier`` (the text then says what it is, "In cassatie op : ECLI:..."),
    else its text or the ``id=`` of its ``rdf:resource``."""
    attributes = {local_name(name): value for name, value in element.attrib.items()}
    ecli = (attributes.get("resourceIdentifier") or element.text or "").strip()
    if not ecli.upper().startswith("ECLI:"):
        resource = attributes.get("resource", "")
        ecli = resource.split("id=")[-1].strip() if "id=" in resource else ""
    return ecli.upper() if ecli.upper().startswith("ECLI:") else None


def is_earlier_instance(element: ET.Element) -> bool:
    """Is the judgment a relation names one this judgment ruled on appeal of?

    Not the conclusion of the Advocate General (``psi:type`` .../conclusie), and not a later
    instance (``psi:aanleg`` .../latereAanleg); a relation that says neither counts.
    """
    attributes = {local_name(name): value for name, value in element.attrib.items()}
    return not attributes.get("type", "").endswith("/conclusie") and not attributes.get(
        "aanleg", ""
    ).endswith("/latereAanleg")


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
            if ecli and is_earlier_instance(el):
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
#
# A judgment numbers its considerations (overwegingen): "5.3" is the third paragraph of the
# fifth section, cited as "rov. 5.3". The XML writes the number as ``<nr>`` in a
# ``<paragroup>`` (a numbered unit, nested as deep as the numbering goes) or in the
# ``<title>`` of a ``<section>``; many courts put it in front of the text of a ``<para>``
# instead ("1.    Bij het besluit ..."). Both are read as the printed number of a paragraph.

KIND_HEADING = "heading"
KIND_SUBHEADING = "subheading"
KIND_BODY = "body"

# "5.3 text", "12. text": digits, a dot or a dotted number, then a space. A number alone
# ("1 februari 2013") is not one: a date opens a sentence too.
_LEADING_NUMBER = re.compile(r"^(\d{1,3}(?:\.\d{1,2})+\.?|\d{1,3}\.)\s+(?=\S)")
_NOT_TEXT = {"title", "footnote", "nr"}
_BLOCKS = {"para", "parablock", "paragroup", "list", "li", "table", "al"}


def _slug(number: str) -> str:
    """The printed number as written in an id: ``"5.3."`` is ``"5.3"``."""
    return re.sub(r"[^0-9a-z.]", "", number.lower()).strip(".")


def _flat(element: ET.Element) -> str:
    """The text of an element on one line; inline markup stays inside the word."""
    blocks = any(local_name(child.tag) in _BLOCKS for child in element)
    return collapse_ws(text_of(element, " " if blocks else ""))


def _unit_text(element: ET.Element) -> str:
    """The text of a ``<para>`` or ``<parablock>``: its paragraphs, a blank line between."""
    paras = [_flat(p) for p in iter_named(element, "para") if not len(p)] or [
        _flat(element)
    ]
    return "\n\n".join(p for p in paras if p)


def _split_number(text: str) -> tuple[str | None, str]:
    """``("5.3", "text")`` for text that opens with a printed number, else ``(None, text)``."""
    match = _LEADING_NUMBER.match(text)
    if not match:
        return None, text
    return match[1].rstrip("."), text[match.end() :]


class _Sections:
    """The paragraphs of an ``<uitspraak>``, in reading order."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._seen: dict[str, int] = {}

    def add(self, kind: str, number: str | None, text: str) -> None:
        if not text and not number:
            return
        slug = _slug(number) if number else ""
        if slug:
            base = f"{'rov' if kind == KIND_BODY else 'kop'}-{slug}"
        else:
            number, base = None, f"p-{len(self.entries) + 1}"
        self._seen[base] = self._seen.get(base, 0) + 1
        paragraph_id = base if self._seen[base] == 1 else f"{base}_{self._seen[base]}"
        self.entries.append(
            {"id": paragraph_id, "number": number, "kind": kind, "text": text}
        )

    def unnumbered(self, kind: str, text: str) -> None:
        """A paragraph that may open with its number."""
        number, rest = _split_number(text)
        self.add(kind, number, rest)

    def walk(self, container: ET.Element, depth: int = 0) -> None:
        """Every child of an ``<uitspraak>``, a ``<section>`` or a ``<paragroup>``."""
        for child in container:
            name = local_name(child.tag)
            if name == "section":
                self.section(child, depth)
            elif name == "paragroup":
                self.paragroup(child, depth)
            elif name == "uitspraak.info":
                self.add(KIND_SUBHEADING, None, _unit_text(child))
            elif name == "parablock":  # a run of paragraphs, each one of its own
                self.walk(child, depth)
            elif name not in _NOT_TEXT:  # para, al and any other body element
                self.unnumbered(KIND_BODY, _flat(child))

    def section(self, section: ET.Element, depth: int) -> None:
        title = next((c for c in section if local_name(c.tag) == "title"), None)
        number, text = None, ""
        if title is not None:
            number = collapse_ws(text_of(first_named(title, "nr"))) or None
            text = collapse_ws(text_of(title, " "))
            if number and text.startswith(number):
                text = text[len(number) :].strip()
        kind = KIND_HEADING if depth == 0 else KIND_SUBHEADING
        self.add(kind, number, text)
        self.walk(section, depth + 1)

    def paragroup(self, group: ET.Element, depth: int) -> None:
        """A numbered unit: its own paragraphs are one entry, nested units follow."""
        nr = next((c for c in group if local_name(c.tag) == "nr"), None)
        number = collapse_ws(text_of(nr)) or None
        if number is None:
            self.walk(group, depth)
            return
        own: list[str] = []
        for child in group:
            name = local_name(child.tag)
            if name in ("paragroup", "section"):
                self.flush(number, own)
                (self.paragroup if name == "paragroup" else self.section)(child, depth)
            elif name not in _NOT_TEXT and name != "uitspraak.info":
                own.append(_unit_text(child))
        self.flush(number, own)

    def flush(self, number: str, own: list[str]) -> None:
        text = "\n\n".join(t for t in own if t)
        own.clear()
        if text:
            self.add(KIND_BODY, number, text)


def extract_sections(root: ET.Element) -> list[dict[str, Any]]:
    """The paragraphs of the first ``<uitspraak>``: ``{id, number, kind, text}`` each.

    ``kind`` is ``heading`` (a section), ``subheading`` (a nested section or an
    ``<uitspraak.info>`` block) or ``body``. A numbered unit (``<paragroup>``) is one
    ``body`` paragraph however many ``<para>`` it holds, and each nested unit another: the
    text of "5.3" does not contain "5.3.1". ``number`` is the printed number without its
    closing dot (``"5.3"``), null when the paragraph has none, and is not part of ``text``.

    ``id`` names a paragraph in a deep link and is unique in the judgment: ``rov-5.3`` for
    a numbered ``body`` paragraph, ``kop-5`` for a numbered heading, ``p-<n>`` (its
    position) for a paragraph without a number. A number that repeats one before it gets
    ``_<n>``, its occurrence (``rov-1_2``: the judgments of some courts number their
    procedure and their considerations from 1 each).
    """
    uitspraak = first_named(root, "uitspraak")
    sections = _Sections()
    if uitspraak is not None:
        sections.walk(uitspraak)
    return sections.entries


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
