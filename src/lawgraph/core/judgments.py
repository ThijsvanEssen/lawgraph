"""Pure parsing/deriving helpers for Rechtspraak judgments (no I/O, no store)."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
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
# The Parket bij de Hoge Raad: the conclusions of its advocates-general, no judgments.
TIER_PARKET = "parket"
TIER_GERECHTSHOF = "gerechtshof"
TIER_RECHTBANK = "rechtbank"
# Any other court: the Raad van State, the Centrale Raad van Beroep, the CBB, the courts of
# the Caribbean parts, disciplinary courts.
TIER_BIJZONDER = "bijzonder"
TIERS = (TIER_HOGE_RAAD, TIER_PARKET, TIER_GERECHTSHOF, TIER_RECHTBANK, TIER_BIJZONDER)

# The tier of a court code: the code itself, else its first two letters, else bijzonder.
# ``graph-list-stats`` writes the same in AQL from these tables.
TIER_OF_COURT = {"HR": TIER_HOGE_RAAD, "PHR": TIER_PARKET}
TIER_OF_PREFIX = {"GH": TIER_GERECHTSHOF, "RB": TIER_RECHTBANK}


def court_tier(court_code: str | None) -> str | None:
    """The tier of a court (``TIER_OF_COURT``, ``TIER_OF_PREFIX``); ``None`` without one."""
    if not court_code:
        return None
    return TIER_OF_COURT.get(court_code) or TIER_OF_PREFIX.get(
        court_code[:2], TIER_BIJZONDER
    )


def derive_court_tier(ecli: str | None) -> tuple[str | None, str | None]:
    """Return ``(court_code, tier)`` derived from the ECLI identifier."""
    if not ecli:
        return None, None
    parts = ecli.split(":")
    court_code = parts[2].upper() if len(parts) >= 3 else None
    return court_code, court_tier(court_code)


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
        return ET.fromstring((payload_text or "").replace("<?linebreak?>", LINE_BREAK))
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc


def extract_judgment_text(root: ET.Element) -> tuple[str | None, str | None]:
    """Return ``(summary, full_text)`` of a parsed judgment."""
    summary = text_of(first_named(root, "inhoudsindicatie"), " ") or None
    if summary:
        summary = summary.replace(LINE_BREAK, "\n")
    parts = [
        text_of(el, " ").replace(LINE_BREAK, "\n")
        for el in iter_named(root, "uitspraak")
    ]
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


def is_conclusion_relation(element: ET.Element) -> bool:
    """Does the relation tie a conclusion to its judgment (``psi:type`` .../conclusie)?

    A judgment names its conclusion so, and a conclusion the judgment it advised on.
    """
    attributes = {local_name(name): value for name, value in element.attrib.items()}
    return attributes.get("type", "").endswith("/conclusie")


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
    "type": "document_type",  # dcterms:type: "Uitspraak" or "Conclusie"
}

DOCUMENT_TYPE_CONCLUSION = "Conclusie"
PROCEDURE_PRELIMINARY_RULING = "Prejudiciële beslissing"

# The court code of a conclusion -> that of the judgment it advises on, where they differ:
# the Parket bij de Hoge Raad advises the Hoge Raad. Any other court (the Raad van State,
# the Centrale Raad van Beroep) publishes the conclusions of its own advocates-general.
CONCLUSION_BENCH = {"PHR": "HR"}
# Courts that publish nothing but conclusions.
CONCLUSION_ONLY_COURTS = frozenset(CONCLUSION_BENCH)


def extract_rdf_metadata(root: ET.Element) -> tuple[dict[str, Any], list[str]]:
    """Return ``(judgment_metadata, subjects)`` from ``<rdf:Description>``."""
    meta: dict[str, Any] = {}
    subjects: list[str] = []
    related_eclis: list[str] = []
    conclusion_eclis: list[str] = []

    for el in root.iter():
        tag = local_name(el.tag)
        if tag == "relation":
            ecli = relation_ecli(el)
            if ecli and is_conclusion_relation(el):
                conclusion_eclis.append(ecli)
            elif ecli and is_earlier_instance(el):
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
    if conclusion_eclis:
        meta["conclusion_eclis"] = conclusion_eclis
    return meta, subjects


# ── case numbers ─────────────────────────────────────────────────────────────

# Between the case numbers of one judgment: "18/04298 en 18/04299", "200.1, 200.2".
_CASE_NUMBER_SPLIT = re.compile(r"\s*(?:,|;|\ben\b)\s*", re.IGNORECASE)


def case_number_keys(case_number: str | None) -> list[str]:
    """The case numbers of a judgment as compared: lower case, without spaces.

    The same number is written ``C/19/117301 / HA ZA 16-256`` in the metadata of one
    judgment and ``C/19/117301/HA ZA 16-256`` in the text of another.
    """
    keys: list[str] = []
    for part in _CASE_NUMBER_SPLIT.split(case_number or ""):
        key = re.sub(r"\s+", "", part).lower()
        if key and any(c.isdigit() for c in key) and key not in keys:
            keys.append(key)
    return keys


# ── the referral of a preliminary ruling ─────────────────────────────────────

_ECLI_IN_TEXT = re.compile(r"\bECLI:NL:[A-Z]{2,8}:\d{4}:[A-Z0-9]{1,8}\b", re.IGNORECASE)
# "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de
# rechtbank ... prejudiciële vragen aan de Hoge Raad gesteld"; "in de zaken 8674876/EJ VERZ
# 20-213 en 8675941 EJ VERZ 20-214 van 8 februari 2021".
_REFERRAL_CASES = re.compile(
    r"\bin\s+de\s+za(?:ak|ken)\s+(?P<numbers>.{3,120}?)\s+van\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    month: number
    for number, month in enumerate(
        (
            "januari",
            "februari",
            "maart",
            "april",
            "mei",
            "juni",
            "juli",
            "augustus",
            "september",
            "oktober",
            "november",
            "december",
        ),
        start=1,
    )
}


@dataclass(frozen=True)
class Referral:
    """What a preliminary ruling says of the decision that asked its questions."""

    eclis: tuple[str, ...] = ()
    case_keys: tuple[str, ...] = ()  # as ``case_number_keys`` writes them
    date: str | None = None  # of the referring decision, ISO


def _dutch_date(text: str) -> str | None:
    day, month, year = text.split()
    number = _MONTHS.get(month.lower())
    if number is None:
        return None
    try:
        return dt.date(int(year), number, int(day)).isoformat()
    except ValueError:
        return None


def read_referral(paragraphs: list[dict[str, Any]]) -> Referral | None:
    """The referring decision a preliminary ruling names, from the first paragraph that
    says questions were asked ("prejudiciële vragen ... gesteld"): the ECLIs it names, or
    the case numbers and the date of the decision. ``None`` when no paragraph does.
    """
    for paragraph in paragraphs:
        text = paragraph.get("text") or ""
        lowered = text.lower()
        if "prejudiciële vra" not in lowered or "gesteld" not in lowered:
            continue
        eclis = tuple(dict.fromkeys(e.upper() for e in _ECLI_IN_TEXT.findall(text)))
        match = _REFERRAL_CASES.search(text)
        if not eclis and not match:
            continue
        return Referral(
            eclis=eclis,
            case_keys=tuple(case_number_keys(match["numbers"])) if match else (),
            date=_dutch_date(match["date"]) if match else None,
        )
    return None


# ── <uitspraak> structure ────────────────────────────────────────────────────
#
# A judgment numbers its considerations (overwegingen): "5.3" is the third paragraph of the
# fifth section, cited as "rov. 5.3". The XML writes the number as ``<nr>`` in a
# ``<paragroup>`` (a numbered unit, nested as deep as the numbering goes) or in the
# ``<title>`` of a ``<section>``; many courts put it in front of the text of a ``<para>``
# instead ("1.    Bij het besluit ..."). Both are read as the printed number of a paragraph.
#
# Before the first section heading stands the kop: the court, the case number, the date and
# the parties. Courts write it in an ``<uitspraak.info>``, in loose paragraphs, in
# bridgeheads or in sections whose titles are party names; it is read line by line, whatever
# holds the lines.

KIND_HEADING = "heading"
KIND_SUBHEADING = "subheading"
KIND_BODY = "body"

# "5.3 text", "12. text": digits, a dot or a dotted number, then a space. A number alone
# ("1 februari 2013") is not one: a date opens a sentence too.
_LEADING_NUMBER = re.compile(r"^(\d{1,3}(?:\.\d{1,2})+\.?|\d{1,3}\.)\s+(?=\S)")
_NOT_TEXT = {"title", "footnote", "nr"}
_BLOCKS = {"para", "parablock", "paragroup", "list", "li", "table", "al"}
# The elements that print a line of their own: paragraphs, bridgeheads (a bold line), the
# titles of sections and the rows of a table.
_LINE_ELEMENTS = {"para", "bridgehead", "title", "row"}

# The line that ends the kop: the heading of the first section, numbered or not ("1 Het
# verloop van de procedure", "Procesverloop", "Onderzoek van de zaak", "SAMENVATTING").
_SECTION_HEADING = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2})*\.?\s*|[IVX]{1,4}[.)]?\s+|[A-Z][.)]\s*)?(?:"
    r"(?:het\s+)?proces-?verloop|procesgang|(?:de\s+)?(?:\w+\s+)?procedure\b|"
    r"(?:het\s+)?(?:verdere?\s+)?verloop\s+van\s+(?:de|het)\b|(?:de\s+)?loop\s+van\s+het\s+geding|"
    r"(?:het\s+)?ontstaan\s+en\s+(?:de\s+)?loop\b|"
    r"(?:het\s+)?onderzoek\s+(?:van\s+de\s+zaak|ter\s+(?:terecht)?zitting|op\s+de\s+)|"
    r"(?:de\s+)?samenvatting|inleiding|overwegingen|(?:de\s+)?beoordeling|"
    r"(?:de\s+)?tenlastelegging|(?:het\s+)?geding\s+in\b|(?:het\s+)?hoger\s+beroep$|"
    r"(?:de\s+)?(?:vaststaande\s+)?feiten\b|(?:het\s+)?geschil\b|"
    r"waar\s+gaat\s+(?:de(?:ze)?\s+zaak|het)\s+over|(?:de\s+)?zaak\s+in\s+het\s+kort|"
    r"verzoek\s+en\s+verweer|(?:de\s+)?uitgangspunten|(?:de\s+)?zitting$|"
    r"(?:het\s+)?vonnis\s+waarvan\s+beroep|(?:de\s+)?beslissing\s+van\s+de\s+kantonrechter|"
    r"(?:het\s+|de\s+)?(?:bestreden|aangevallen)\s+(?:vonnis|arrest|uitspra(?:ak|ken)|"
    r"beschikking|besluit)|(?:het\s+)?geding$|inhoudsopgave|"
    r"(?:de\s+)?inhoud\s+van\s+het\s+(?:verzoek|klaagschrift|beroep)|"
    r"(?:het\s+|de\s+)?(?:eerdere\s+)?tussen(?:arrest|vonnis|uitspraak|beschikking)$"
    r")",
    re.IGNORECASE,
)
# The kop names parties, a hundred in a mass claim, but tells no story: text before the
# first heading with more lines of prose than this is no kop (old judgments put their
# first heading late, or not at all).
KOP_MAX_PROSE_LINES = 4
PROSE_LINE_CHARS = 200

# A <?linebreak?> in the XML: a line break inside a paragraph. ``parse_judgment`` keeps it
# as this character (whitespace to ``collapse_ws``), which the kop splits its lines at.
LINE_BREAK = "\u2028"


def _slug(number: str) -> str:
    """The printed number as written in an id: ``"5.3."`` is ``"5.3"``."""
    return re.sub(r"[^0-9a-z.]", "", number.lower()).strip(".")


def _flat(element: ET.Element) -> str:
    """The text of an element on one line; inline markup stays inside the word."""
    blocks = any(local_name(child.tag) in _BLOCKS for child in element)
    return collapse_ws(text_of(element, " " if blocks else ""))


def _unit_text(
    element: ET.Element, skip: set[int] | frozenset[int] = frozenset()
) -> str:
    """The text of a ``<para>`` or ``<parablock>``: its paragraphs, a blank line between.

    A ``<para>`` holds no other blocks, only inline markup (emphasis, footnote references,
    links); the paragraphs in *skip* were read into the kop.
    """
    paras = list(iter_named(element, "para", "bridgehead"))
    if not paras:
        return _flat(element)
    return "\n\n".join(t for p in paras if id(p) not in skip and (t := _flat(p)))


def _split_number(text: str) -> tuple[str | None, str]:
    """``("5.3", "text")`` for text that opens with a printed number, else ``(None, text)``."""
    match = _LEADING_NUMBER.match(text)
    if not match:
        return None, text
    return match[1].rstrip("."), text[match.end() :]


def _line_elements(element: ET.Element) -> Iterator[ET.Element]:
    """The elements of *element* that print a line (``_LINE_ELEMENTS``), in reading order;
    footnotes left out."""
    for child in element:
        name = local_name(child.tag)
        if name in _LINE_ELEMENTS:
            yield child
        elif name != "footnote":
            yield from _line_elements(child)


def _printed_lines(element: ET.Element) -> list[str]:
    """The lines a line element prints: split at its line breaks; a title or a table row
    is one line, its parts a space apart."""
    sep = " " if local_name(element.tag) in ("title", "row") else ""
    parts = (collapse_ws(part) for part in text_of(element, sep).split(LINE_BREAK))
    return [part for part in parts if part]


def is_section_heading(line: str) -> bool:
    """Does *line* open the first section of a judgment, and so end its kop?"""
    return len(line) <= 90 and bool(_SECTION_HEADING.match(line))


def _read_kop(uitspraak: ET.Element) -> tuple[list[str], set[int]]:
    """``(lines, elements)`` of the kop: every line before the first section heading, and
    the ids of the elements that print them. Nothing when no heading ends it, or only
    after more than ``KOP_MAX_PROSE_LINES`` lines of prose: a judgment without headings has
    no kop to tell apart.
    """
    lines: list[str] = []
    elements: set[int] = set()
    prose = 0
    for element in _line_elements(uitspraak):
        printed = _printed_lines(element)
        if printed and is_section_heading(printed[0]):
            return lines, elements
        prose += sum(len(line) > PROSE_LINE_CHARS for line in printed)
        if prose > KOP_MAX_PROSE_LINES:
            break
        lines.extend(printed)
        elements.add(id(element))
    return [], set()


def kop_lines(root: ET.Element) -> list[str]:
    """The lines of the kop of the first ``<uitspraak>`` (see ``_read_kop``)."""
    uitspraak = first_named(root, "uitspraak")
    return _read_kop(uitspraak)[0] if uitspraak is not None else []


class _Sections:
    """The paragraphs of an ``<uitspraak>``, in reading order."""

    def __init__(self, kop: set[int]) -> None:
        self.entries: list[dict[str, Any]] = []
        self._seen: dict[str, int] = {}
        self._kop = kop  # the elements read into the kop

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
            if id(child) in self._kop:
                continue
            if name == "section":
                self.section(child, depth)
            elif name == "paragroup":
                self.paragroup(child, depth)
            elif name in ("uitspraak.info", "parablock"):
                # the kop, when a court writes the judgment in it, or a run of paragraphs
                self.walk(child, depth)
            elif name == "bridgehead":
                self.add(
                    KIND_HEADING if depth == 0 else KIND_SUBHEADING, None, _flat(child)
                )
            elif name not in _NOT_TEXT:  # para, al and any other body element
                self.unnumbered(KIND_BODY, _unit_text(child, self._kop))

    def section(self, section: ET.Element, depth: int) -> None:
        title = next((c for c in section if local_name(c.tag) == "title"), None)
        if title is not None and id(title) not in self._kop:
            number = collapse_ws(text_of(first_named(title, "nr"))) or None
            text = collapse_ws(text_of(title, " "))
            if number and text.startswith(number):
                text = text[len(number) :].strip()
            self.add(KIND_HEADING if depth == 0 else KIND_SUBHEADING, number, text)
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
            elif name not in _NOT_TEXT and id(child) not in self._kop:
                own.append(_unit_text(child, self._kop))
        self.flush(number, own)

    def flush(self, number: str, own: list[str]) -> None:
        text = "\n\n".join(t for t in own if t)
        own.clear()
        if text:
            self.add(KIND_BODY, number, text)


def extract_sections(root: ET.Element) -> list[dict[str, Any]]:
    """The paragraphs of the first ``<uitspraak>``: ``{id, number, kind, text}`` each.

    ``kind`` is ``heading`` (a section or a bridgehead), ``subheading`` (a nested one, or
    the kop) or ``body``. The kop (``_read_kop``), when the judgment has one, is the first
    paragraph: a ``subheading`` of its lines, a blank line between. A numbered unit
    (``<paragroup>``) is one ``body`` paragraph however many ``<para>`` it holds, and each
    nested unit another: the text of "5.3" does not contain "5.3.1". ``number`` is the
    printed number without its closing dot (``"5.3"``), null when the paragraph has none,
    and is not part of ``text``.

    ``id`` names a paragraph in a deep link and is unique in the judgment: ``rov-5.3`` for
    a numbered ``body`` paragraph, ``kop-5`` for a numbered heading, ``p-<n>`` (its
    position) for a paragraph without a number. A number that repeats one before it gets
    ``_<n>``, its occurrence (``rov-1_2``: the judgments of some courts number their
    procedure and their considerations from 1 each).
    """
    uitspraak = first_named(root, "uitspraak")
    if uitspraak is None:
        return []
    lines, kop = _read_kop(uitspraak)
    sections = _Sections(kop)
    sections.add(KIND_SUBHEADING, None, "\n\n".join(lines))
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
