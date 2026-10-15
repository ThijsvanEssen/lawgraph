"""What a Rechtspraak judgment XML says of itself: the parsed root, its summary and text,
its RDF metadata and relations, the court, the area of law and the language of its
summary. Pure: no I/O, no store."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.courts import court_of
from lawgraph.core.ecli import court_code
from lawgraph.core.xml import collapse_ws, first_named, iter_named, local_name, text_of

# ── ECLI-derived attributes ──────────────────────────────────────────────────


def derive_court(
    ecli: str | None, court: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """``(court_code, tier, court_kind)`` of a judgment, from its ECLI and the court its
    metadata names (``core.courts.court_of``); the tier and kind ``None`` for a code the
    court table does not know."""
    if not ecli:
        return None, None, None
    code = court_code(ecli)
    found = court_of(code, court)
    return (
        code,
        found.tier if found else None,
        found.court_kind if found else None,
    )


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

# A <?linebreak?> in the XML: a line break inside a paragraph. ``parse_judgment`` keeps it
# as this character (whitespace to ``collapse_ws``), which the kop splits its lines at.
LINE_BREAK = " "


def parse_judgment(payload_text: str | None) -> ET.Element:
    """The root of a judgment XML; ``ValueError`` when *payload_text* is not XML.

    Parsed once by the caller and handed to the extractors below: a judgment that cannot
    be read must not become a judgment without court, date and text.
    """
    try:
        return ET.fromstring((payload_text or "").replace("<?linebreak?>", LINE_BREAK))
    except ET.ParseError as exc:
        raise ValueError(f"not XML: {exc}") from exc


# What a court writes as inhoudsindicatie before it has one: no summary.
_PLACEHOLDER_SUMMARIES = frozenset({"kopje volgt"})


def is_placeholder_summary(summary: str | None) -> bool:
    """Whether an inhoudsindicatie only holds a place: empty, dashes or dots, or a known
    placeholder ("kopje volgt")."""
    plain = collapse_ws(summary).lower().rstrip(".")
    return not plain.strip("-. ") or plain in _PLACEHOLDER_SUMMARIES


def extract_judgment_text(root: ET.Element) -> tuple[str | None, str | None]:
    """Return ``(summary, full_text)`` of a parsed judgment; a placeholder
    inhoudsindicatie ("kopje volgt", "-") is no summary."""
    summary = text_of(first_named(root, "inhoudsindicatie"), " ") or None
    if is_placeholder_summary(summary):
        summary = None
    if summary:
        summary = summary.replace(LINE_BREAK, "\n")
    parts = [text_of(el, " ").replace(LINE_BREAK, "\n") for el in judgment_bodies(root)]
    full_text = "\n\n".join(p for p in parts if p) or None
    return summary, full_text


def judgment_bodies(root: ET.Element) -> list[ET.Element]:
    """The ``<uitspraak>`` elements of a judgment, or the ``<conclusie>`` of a conclusion of
    an advocate-general (which has no ``<uitspraak>``)."""
    return list(iter_named(root, "uitspraak")) or list(iter_named(root, "conclusie"))


def body_text(root: ET.Element) -> str:
    """The text a court or advocate-general wrote: the ``<uitspraak>`` and ``<conclusie>``,
    without the metadata. What a judgment names there it cites; the ECLIs of the metadata
    (``dcterms:relation``: the earlier instance, the conclusion) are procedure, not citation."""
    parts = [
        text_of(el, " ")
        for name in ("uitspraak", "conclusie")
        for el in iter_named(root, name)
    ]
    return "\n\n".join(p for p in parts if p)


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


def is_later_instance(element: ET.Element) -> bool:
    """Is the judgment a relation names a later instance of this one (``psi:aanleg``
    .../latereAanleg): the court that ruled on appeal of it, in cassation or after it?"""
    attributes = {local_name(name): value for name, value in element.attrib.items()}
    return not attributes.get("type", "").endswith("/conclusie") and attributes.get(
        "aanleg", ""
    ).endswith("/latereAanleg")


# dc:/psi: element -> judgment_metadata field; the first non-empty one wins.
_METADATA_FIELDS = {
    "creator": "court",
    "date": "date",
    "zaaknummer": "case_number",
    "procedure": "type",
    "type": "document_type",  # dcterms:type: "Uitspraak" or "Conclusie"
    # the publication of the same decision that replaces this one ("Vervangen door")
    "isReplacedBy": "replaced_by",
}

DOCUMENT_TYPE_CONCLUSION = "Conclusie"
PROCEDURE_PRELIMINARY_RULING = "Prejudiciële beslissing"

# The court code of a conclusion -> that of the judgment it advises on, where they differ:
# the Parket bij de Hoge Raad advises the Hoge Raad. Any other court (the Raad van State,
# the Centrale Raad van Beroep) publishes the conclusions of its own advocates-general.
CONCLUSION_BENCH = {"PHR": "HR"}
# Courts that publish nothing but conclusions.
CONCLUSION_ONLY_COURTS = frozenset(CONCLUSION_BENCH)


def replacing_ecli(value: str | None) -> str | None:
    """The ECLI of ``dcterms:isReplacedBy``: the publication of the same decision that
    replaces this one (an arrest published again under a new ECLI). None when it names
    none, or no ECLI."""
    ecli = (value or "").strip().upper()
    return ecli if ecli.startswith("ECLI:") else None


def extract_rdf_metadata(root: ET.Element) -> tuple[dict[str, Any], list[str]]:
    """Return ``(judgment_metadata, subjects)`` from ``<rdf:Description>``."""
    meta: dict[str, Any] = {}
    subjects: list[str] = []
    related_eclis: list[str] = []
    later_eclis: list[str] = []
    conclusion_eclis: list[str] = []

    for el in root.iter():
        tag = local_name(el.tag)
        if tag == "relation":
            ecli = relation_ecli(el)
            if ecli and is_conclusion_relation(el):
                conclusion_eclis.append(ecli)
            elif ecli and is_later_instance(el):
                later_eclis.append(ecli)
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
    if later_eclis:
        meta["later_eclis"] = later_eclis
    if conclusion_eclis:
        meta["conclusion_eclis"] = conclusion_eclis
    return meta, subjects


_RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"


def published_on(root: ET.Element) -> str | None:
    """The day the judgment was published on uitspraken.rechtspraak.nl ("Datum
    publicatie"), as the source writes it (``2022-02-25``): ``dcterms:issued`` of the
    ``rdf:Description`` about the published document (``rdf:about``, its deeplink). The
    first ``rdf:Description``, about the ECLI, has an ``issued`` of its own that is not it
    (it can be before the judgment's date). None for a record without the document."""
    for element in root.iter():
        if local_name(element.tag) != "Description" or not element.get(_RDF_ABOUT):
            continue
        for child in element:
            if local_name(child.tag) == "issued" and (child.text or "").strip():
                return (child.text or "").strip()
    return None


# ── the area of law ──────────────────────────────────────────────────────────

AREA_CRIMINAL = "Strafrecht"
AREA_CIVIL = "Civiel recht"
AREA_ADMINISTRATIVE = "Bestuursrecht"


def area_of_law(subjects: list[str] | None) -> str | None:
    """The area of law of a judgment: the first part of its first subject."""
    for subject in subjects or []:
        area = subject.split(";")[0].strip()
        if area in (AREA_CRIMINAL, AREA_CIVIL, AREA_ADMINISTRATIVE):
            return area
    return None


# ── the language of a summary ────────────────────────────────────────────────
#
# The Rechtspraak publishes a few judgments in an English translation as well, under an
# ECLI of their own: the case number ends in "(Engels)" or "(English translation)" and the
# inhoudsindicatie is English, although the metadata says ``nl``. Only the words tell.

# Short words of one language that are rare in the other ("in", "is", "of" are both).
_DUTCH_WORDS = frozenset(
    "de het een en van op dat die niet met voor zijn aan door ook bij als er te naar "
    "wordt worden werd heeft hebben".split()
)
_ENGLISH_WORDS = frozenset(
    "the an and that which not with for are to by also at or be was were has have "
    "this from".split()
)
_WORD = re.compile(r"[a-z]+")
MIN_ENGLISH_WORDS = 3


def is_english(text: str | None) -> bool:
    """Whether *text* is English: at least ``MIN_ENGLISH_WORDS`` English words, and more
    than twice as many as Dutch ones."""
    words = _WORD.findall((text or "").lower())
    english = sum(word in _ENGLISH_WORDS for word in words)
    dutch = sum(word in _DUTCH_WORDS for word in words)
    return english >= MIN_ENGLISH_WORDS and english > 2 * dutch
