"""Pure parsing/deriving helpers for Rechtspraak judgments (no I/O, no store)."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lawgraph.core.courts import court_of
from lawgraph.core.xml import (
    collapse_ws,
    first_named,
    iter_named,
    local_name,
    text_of,
)

# ── ECLI-derived attributes ──────────────────────────────────────────────────


def derive_court(
    ecli: str | None, court: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """``(court_code, tier, court_kind)`` of a judgment, from its ECLI and the court its
    metadata names (``core.courts.court_of``); the tier and kind ``None`` for a code the
    court table does not know."""
    if not ecli:
        return None, None, None
    parts = ecli.split(":")
    court_code = parts[2].upper() if len(parts) >= 3 else None
    found = court_of(court_code, court)
    return (
        court_code,
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
    plain = " ".join((summary or "").split()).lower().rstrip(".")
    return not plain.strip("-. ") or plain in _PLACEHOLDER_SUMMARIES


def extract_judgment_text(root: ET.Element) -> tuple[str | None, str | None]:
    """Return ``(summary, full_text)`` of a parsed judgment; a placeholder
    inhoudsindicatie ("kopje volgt", "-") is no summary."""
    summary = text_of(first_named(root, "inhoudsindicatie"), " ") or None
    if is_placeholder_summary(summary):
        summary = None
    if summary:
        summary = summary.replace(LINE_BREAK, "\n")
    parts = [text_of(el, " ").replace(LINE_BREAK, "\n") for el in _bodies(root)]
    full_text = "\n\n".join(p for p in parts if p) or None
    return summary, full_text


def _bodies(root: ET.Element) -> list[ET.Element]:
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


# ── the kind of decision ─────────────────────────────────────────────────────
#
# What a decision is called: a court of cassation or appeal gives an arrest, a court of
# first instance a vonnis, a court on a request (verzoekschrift) a beschikking, an
# administrative court an uitspraak, the advocate-general a conclusie, and the Hoge Raad
# answers the questions of a lower court in a prejudiciële beslissing. The kantonrechter
# rules on an appeal against a traffic fine (Wahv) in a beslissing.

KIND_ARREST = "arrest"
KIND_VONNIS = "vonnis"
KIND_BESCHIKKING = "beschikking"
KIND_UITSPRAAK = "uitspraak"
KIND_CONCLUSIE = "conclusie"
KIND_PRELIMINARY_RULING = "prejudiciële beslissing"
KIND_BESLISSING = "beslissing"
DECISION_KINDS: tuple[str, ...] = (
    KIND_ARREST,
    KIND_VONNIS,
    KIND_BESCHIKKING,
    KIND_UITSPRAAK,
    KIND_BESLISSING,
    KIND_CONCLUSIE,
    KIND_PRELIMINARY_RULING,
)

# The curated kinds (``data/curated/decision_kinds.json``): the kind a procedure
# (``psi:procedure``) names where the kop does not; the kind a kind of court gives when
# nothing else tells (by ``court_kind``: a tier of one kind of court is its own); the kinds
# of court of every area of law, which give an uitspraak in administrative law (tax law too).
DECISION_KINDS_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "curated" / "decision_kinds.json"
)
_CURATED_KINDS: dict[str, Any] = json.loads(
    DECISION_KINDS_FILE.read_text(encoding="utf-8")
)
KIND_OF_PROCEDURE: dict[str, str] = _CURATED_KINDS["procedures"]
KIND_OF_COURT_KIND: dict[str, str] = _CURATED_KINDS["kinds"]
_GENERAL_COURTS = frozenset(_CURATED_KINDS["general_courts"])

# A kop line that names the decision: "Arrest", "ARREST", "Uitspraak op het hoger beroep
# van:", "beschikking van de meervoudige kamer", "Tussenvonnis", "beslissing van de
# kantonrechter". Not a label with its value
# ("Uitspraak : 10 augustus 2026", "Uitspraak d.d. : 28 augustus 2026").
_KIND_LINE = re.compile(
    r"^(?:tussen|eind|deel|herstel|verstek)?"
    r"(arrest|vonnis|beschikking|uitspraak|beslissing(?=\s+van\b))\b"
    r"(?!\s*(?:d\.d\.|datum)?\s*:)",
    re.IGNORECASE,
)
# What follows the kind in a line that may only give the date of the decision: "Uitspraak
# van 21 september 2026" above "Arrest van de meervoudige kamer voor strafzaken".
_ONLY_A_DATE = re.compile(
    r"\s*(?:van|d\.d\.)?\s*\d{1,2}\s+[a-z]+\s+\d{4}\.?\s*", re.IGNORECASE
)


def kind_in_kop(lines: list[str]) -> str | None:
    """The kind the kop names (``_KIND_LINE``): the first line that names one, one with no
    more than a date after the kind only when no other line names one. ``None`` when none
    does."""
    dated: str | None = None
    for line in lines:
        match = _KIND_LINE.match(line.strip())
        if match is None:
            continue
        if not _ONLY_A_DATE.fullmatch(line.strip()[match.end() :]):
            return match[1].lower()
        dated = dated or match[1].lower()
    return dated


def kind_of_court(court_kind: str | None, area: str | None = None) -> str | None:
    """The kind a kind of court gives (``KIND_OF_COURT_KIND``); a court of every area gives
    an uitspraak in administrative law."""
    if court_kind in _GENERAL_COURTS and area == AREA_ADMINISTRATIVE:
        return KIND_UITSPRAAK
    return KIND_OF_COURT_KIND.get(court_kind or "")


def decision_kind(
    *,
    document_type: str | None,
    procedure: str | None,
    kop: list[str],
    court_kind: str | None,
    subjects: list[str] | None,
) -> str | None:
    """The kind of a decision (``DECISION_KINDS``), from the first that tells: the document
    type (``Conclusie``), the procedure (``Prejudiciële beslissing``), the kop (the line that
    names the decision), the procedure again (``Beschikking``, ``Raadkamer``, ...), and last
    the kind of court and the area of law (``kind_of_court``). ``None`` when none does."""
    if document_type == DOCUMENT_TYPE_CONCLUSION:
        return KIND_CONCLUSIE
    if procedure == PROCEDURE_PRELIMINARY_RULING:
        return KIND_PRELIMINARY_RULING
    return (
        kind_in_kop(kop)
        or KIND_OF_PROCEDURE.get(procedure or "")
        or kind_of_court(court_kind, area_of_law(subjects))
    )


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


# "19/00135 (Engels)", "C/09/456689 / HA ZA 13-1396 (English translation)": what a
# translation adds to the case number of the judgment it translates.
_TRANSLATION_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def translated_case_number(case_number: str | None) -> str | None:
    """The case number of the judgment a translation translates: its own without the
    closing remark in brackets. ``None`` when it has none."""
    if not case_number or not _TRANSLATION_SUFFIX.search(case_number):
        return None
    return _TRANSLATION_SUFFIX.sub("", case_number) or None


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

# The paragraphs a ruling tells its referral in: the start ("1 De prejudiciële procedure"),
# after the parties and, when two courts asked, the procedure of each.
REFERRAL_PARAGRAPHS = 40
_ECLI_IN_TEXT = re.compile(r"\bECLI:NL:[A-Z]{2,8}:\d{4}:[A-Z0-9]{1,8}\b", re.IGNORECASE)
_DATE = r"\d{1,2}\s+[a-z]+\s+\d{4}"
# "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de
# rechtbank ... prejudiciële vragen aan de Hoge Raad gesteld"; "in de zaken 8674876/EJ VERZ
# 20-213 en 8675941 EJ VERZ 20-214 van 8 februari 2021"; "verwijst de Hoge Raad naar de
# beschikkingen in de zaak 4986381\EJ VERZ 16-142 en 5026511\EJ VERZ 16-163 van de
# kantonrechter te Enschede van 26 april 2016 en 20 mei 2016".
_CASE_THEN_DATE = re.compile(
    rf"\bin\s+de\s+za(?:ak|ken)\s+(?P<numbers>.{{3,160}}?)\s+van\s+(?P<date>{_DATE})"
    rf"(?:\s+en\s+(?P<last>{_DATE}))?",
    re.IGNORECASE,
)
# "Bij tussenvonnis van 14 november 2024 met zaaknummer C/15/351661 / KG ZA 24-199 heeft";
# "Bij tussenuitspraak van 28 april 2023, in zaak nr. 22/2463T, heeft".
_DATE_THEN_CASE = re.compile(
    rf"\bvan\s+(?P<date>{_DATE}),?\s+(?:met\s+zaaknummers?|in\s+(?:de\s+)?zaak\s+nr\.?)"
    r"\s+(?P<numbers>.{3,120}?)\s*(?:,|\bheeft\b)",
    re.IGNORECASE,
)
# The criminal chamber, in its heading: "op de door de rechtbank Noord-Nederland bij
# beslissing van 19 december 2022, nummers 18-018510-21, 18-298097-21 en 18-298079-21,
# gestelde rechtsvragen".
_DECISION_NUMBERS = re.compile(
    rf"\bbij\s+beslissing\s+van\s+(?P<date>{_DATE}),\s+(?:parket)?nummers?\s+"
    r"(?P<numbers>.{3,160}?),\s+gestelde\b",
    re.IGNORECASE,
)
_REFERRAL_FORMS = (_CASE_THEN_DATE, _DATE_THEN_CASE, _DECISION_NUMBERS)
# Where the case numbers of "in de zaak X van de rechtbank Y van <date>" end.
_COURT_AFTER_NUMBERS = re.compile(r"\s+van\s+(?:de|het)\s", re.IGNORECASE)
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
    """What a preliminary ruling says of a decision that asked its questions."""

    eclis: tuple[str, ...] = ()
    case_numbers: tuple[str, ...] = ()  # as the text writes them
    date: str | None = None  # of the referring decision, ISO

    def names(self, case_number: str | None) -> bool:
        """Whether *case_number* (of a judgment, one or more) is one this referral names."""
        return any(same_case_number(own, case_number) for own in self.case_numbers)


def _dutch_date(text: str) -> str | None:
    day, month, year = text.split()
    number = _MONTHS.get(month.lower())
    if number is None:
        return None
    try:
        return dt.date(int(year), number, int(day)).isoformat()
    except ValueError:
        return None


def _cases_and_date(text: str) -> tuple[re.Match[str] | None, tuple[str, ...]]:
    """The first referral form *text* has, and the case numbers it names."""
    for form in _REFERRAL_FORMS:
        if match := form.search(text):
            numbers = _COURT_AFTER_NUMBERS.split(match["numbers"])[0]
            parts = (collapse_ws(p) for p in _CASE_NUMBER_SPLIT.split(numbers))
            return match, tuple(p for p in parts if p)
    return None, ()


def _referral_of(text: str, referred: Referral | None) -> Referral | None:
    """The referral one paragraph states, if it says questions were asked ("prejudiciële
    vragen ... gesteld", "prejudiciële beslissing op de ... gestelde rechtsvragen").
    *referred* is what an earlier paragraph pointed to ("verwijst ... naar het vonnis in de
    zaak ..."), which "bij laatstgenoemd vonnis" takes up."""
    lowered = text.lower()
    if "prejudici" not in lowered or "gesteld" not in lowered:
        return None
    eclis = tuple(dict.fromkeys(e.upper() for e in _ECLI_IN_TEXT.findall(text)))
    if eclis:
        return Referral(eclis=eclis)
    match, numbers = _cases_and_date(text)
    if match and numbers:
        return Referral(case_numbers=numbers, date=_dutch_date(match["date"]))
    if "laatstgenoemd" in lowered:
        return referred
    return None


def _referred_to(text: str) -> Referral | None:
    """The decision of the lower court a paragraph points to, at the last of its dates."""
    match, numbers = _cases_and_date(text)
    if match is None or not numbers:
        return None
    last = match.groupdict().get("last") or match["date"]
    return Referral(case_numbers=numbers, date=_dutch_date(last))


def read_referrals(paragraphs: list[dict[str, Any]]) -> list[Referral]:
    """The referring decisions a preliminary ruling names, from the paragraphs that say
    questions were asked: the ECLIs they name, or the case numbers and the date of the
    decision. A ruling that answers two courts names two.
    """
    referrals: list[Referral] = []
    referred: Referral | None = None
    for paragraph in paragraphs:
        text = paragraph.get("text") or ""
        referral = _referral_of(text, referred)
        if referral is None and "verwijst" in text.lower():
            referred = _referred_to(text) or referred
        elif referral is not None and referral not in referrals:
            referrals.append(referral)
    return referrals


# What keeps a case number recognisable once punctuation, spaces, a "/01" suffix or the
# initials of a clerk ("MvW/JE") are left out: a number of five digits or more
# ("C/09/610280", "200.273.775", the "018510" of parketnummer 18-018510-21), else a roll
# number of a year and four digits or more ("22/2463T", "20-9656").
_STRONG_DIGITS = 5
_DIGITS = re.compile(r"\d+")
_DOTTED_NUMBER = re.compile(r"\d+(?:\.\d+)+")
_ROLL_NUMBER = re.compile(r"(?<![0-9a-z])(\d{2})\s*[/-]\s*(\d{4,6}[a-z]?)(?![0-9a-z])")
_NOT_ALNUM = re.compile(r"[^0-9a-z]")


def _case_number_tokens(case_number: str) -> tuple[set[str], set[str]]:
    lowered = case_number.lower()
    runs = _DIGITS.findall(lowered) + [
        number.replace(".", "") for number in _DOTTED_NUMBER.findall(lowered)
    ]
    strong = {run for run in runs if len(run) >= _STRONG_DIGITS}
    rolls = {f"{year}/{number}" for year, number in _ROLL_NUMBER.findall(lowered)}
    return strong, rolls


def same_case_number(named: str, other: str | None) -> bool:
    """Whether the case number *named* in a text is among *other* (the case numbers of a
    judgment, as its metadata or the index writes them).

    They are the same when they share a number of five digits or more; when *named* has
    none, a roll number (``22/2463T``); when it has neither, all its letters and digits.
    """
    if not other:
        return False
    strong, rolls = _case_number_tokens(named)
    other_strong, other_rolls = _case_number_tokens(other)
    if strong:
        return bool(strong & other_strong)
    if rolls:
        return bool(rolls & other_rolls)
    own = _NOT_ALNUM.sub("", named.lower())
    return any(c.isdigit() for c in own) and own == _NOT_ALNUM.sub("", other.lower())


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
KIND_SIGNATURE = "signature"

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
    r"(?:het\s+)?proces-?verloop|(?:de\s+)?procesgang|(?:het\s+)?cassatieberoep$|"
    r"(?:de\s+)?(?:\w+\s+)?procedure\b|"
    r"(?:het\s+)?(?:verdere?\s+)?verloop\s+van\s+(?:de|het)\b|(?:de\s+)?loop\s+van\s+het\s+geding|"
    r"(?:het\s+)?ontstaan\s+en\s+(?:de\s+)?loop\b|"
    r"(?:het\s+)?onderzoek\s+(?:van\s+de\s+zaak|ter\s+(?:terecht)?zitting|op\s+de\s+)|"
    r"(?:de\s+)?samenvatting|inleiding|overwegingen|(?:de\s+)?beoordeling|"
    r"(?:de\s+)?tenlastelegging|(?:het\s+)?geding\s+in\b|(?:het\s+)?hoger\s+beroep$|"
    r"(?:de\s+)?(?:vaststaande\s+)?feiten\b|(?:het\s+)?geschil\b|"
    r"waar\s+gaat\s+(?:de(?:ze)?\s+zaak|het)\s+over|(?:de\s+)?zaak\s+in\s+het\s+kort|"
    r"verzoek\s+en\s+verweer|(?:de\s+)?uitgangspunten|(?:de\s+)?zitting$|"
    r"(?:het\s+)?vonnis\s+waarvan\s+beroep|(?:de\s+)?beslissing\s+van\s+de\s+kantonrechter|"
    r"(?:het\s+|de\s+)?(?:bestreden|aangevallen)\s+(?:vonnis|arrest|"
    r"(?:eind)?uitspra(?:ak|ken)|beschikking|besluit)|(?:het\s+)?geding$|inhoudsopgave|"
    r"(?:de\s+)?(?:uitspraak|beschikking)\s+van\s+(?:het\s+hof|de\s+rechtbank)$|"
    r"(?:de\s+)?inhoud\s+van\s+het\s+(?:verzoek|klaagschrift|beroep)|"
    r"(?:het\s+|de\s+)?(?:eerdere\s+)?tussen(?:arrest|vonnis|uitspraak|beschikking)$|"
    r"(?:lijst\s+van\s+)?(?:gebruikte\s+)?afkortingen$"
    r")",
    re.IGNORECASE,
)
# The element a conclusion writes its kop in: the kop ends with it, if no heading ends it
# before (a list of abbreviations can close it).
_KOP_ELEMENTS = frozenset({"conclusie.info"})
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
    the ids of the elements that print them. When no heading ends it, or only after more
    than ``KOP_MAX_PROSE_LINES`` lines of prose, the ``<conclusie.info>`` of a conclusion
    is its kop, and a judgment has none: without headings there is no kop to tell apart.
    """
    info = next((c for c in uitspraak if local_name(c.tag) in _KOP_ELEMENTS), None)
    in_info = {id(e) for e in _line_elements(info)} if info is not None else set()
    lines: list[str] = []
    elements: set[int] = set()
    info_kop: tuple[list[str], set[int]] = ([], set())
    prose = 0
    for element in _line_elements(uitspraak):
        if not info_kop[0] and elements & in_info and id(element) not in in_info:
            info_kop = (list(lines), set(elements))  # the end of the info
        printed = _printed_lines(element)
        if printed and is_section_heading(printed[0]):
            return lines, elements
        prose += sum(len(line) > PROSE_LINE_CHARS for line in printed)
        if prose > KOP_MAX_PROSE_LINES:
            break
        lines.extend(printed)
        elements.add(id(element))
    return info_kop


def kop_lines(root: ET.Element) -> list[str]:
    """The lines of the kop of the first ``<uitspraak>`` or ``<conclusie>`` (see
    ``_read_kop``)."""
    uitspraak = next(iter(_bodies(root)), None)
    return _read_kop(uitspraak)[0] if uitspraak is not None else []


# ── the advocate-general of a conclusion ─────────────────────────────────────
#
# A conclusion names who wrote it above its parties, a surname with initials or "mr.":
# "T. Hartlief" on a line of its own below CONCLUSIE, "mr. P.J. Wattel" above
# "Advocaat-Generaal", "Zaaknr: 18/04298 (Prejudicieel) mr. Wattel", "Conclusie van den
# Advocaat-Generaal Mr. Besier."; the signature at the end gives only the office.

_INITIALS = r"(?:(?:[A-Z]|IJ|Th|Chr|Ph)\.\s?)+"
_PARTICLE = r"(?:van|de|der|den|ten|ter|het|in\s+'t|'t)"
# A word that follows a name on its line and is no part of it: "Mr. T.N.B.M. Spronken
# Conclusie inzake:", "D.J.C. Aben Vordering tot cassatie".
_AFTER_NAME = (
    r"(?:conclusie|nadere|aanvullende|vordering|zitting|datum|advocaat|procureur|"
    r"raadsheer|staatsraad|parket|en)"
)
_SURNAME = (
    rf"(?:{_PARTICLE}\s+)*[A-Z][\w'’]+"
    rf"(?:(?:-|\s+)(?!(?i:{_AFTER_NAME})\b)(?:{_PARTICLE}[\s-]+)*[A-Z][\w'’]+)*"
)
_PERSON = rf"(?:{_INITIALS})?\s*{_SURNAME}"
# All of a line: "T. Hartlief", "mr. Wattel", "F.F. Langemeijer en M.H. Wissink".
_NAME_LINE = re.compile(
    rf"^(?:(?P<mr>(?i:mr)\.?)\s*)?(?P<name>(?P<initials>{_INITIALS})?\s*{_SURNAME}"
    rf"(?:\s+en\s+{_PERSON})?)\.?$"
)
_NAME_IN_LINE = re.compile(rf"\b(?i:mr)\.?\s+(?P<name>{_PERSON})")
# At the end of a line, with initials: "Zaaknr :26/00083 R.H. de Bock".
_NAME_ENDS_LINE = re.compile(rf"\s(?P<name>{_INITIALS}\s*{_SURNAME})\.?$")
# Where the parties begin: a name after it is theirs, or their lawyer's. Not "inzake
# prejudiciële vraag", which says what the conclusion is on.
_PARTIES_BEGIN = re.compile(
    r"\b(?:inzake|in\s+de\s+za(?:ak|ken)|tussen)\b(?!\s+prejudici)", re.IGNORECASE
)
OPENING_LINES = 20


def _name_in(line: str) -> str | None:
    """The name of a person *line* gives: all of it with initials or "mr." in front, one
    behind "mr." in it, or one with initials that ends it."""
    whole = _NAME_LINE.match(line.strip())
    if whole and (whole["mr"] or whole["initials"]):
        return whole["name"].strip()
    found = _NAME_IN_LINE.search(line) or _NAME_ENDS_LINE.search(line.rstrip())
    return found["name"].strip() if found else None


def advocate_general(root: ET.Element) -> str | None:
    """The advocate-general (or procureur-generaal) who wrote a conclusion, as its first
    ``OPENING_LINES`` lines name them before its parties: "T. Hartlief", "P.J. Wattel", or
    only the surname ("Wattel") where the conclusion gives no more; two who wrote it
    together as one ("F.F. Langemeijer en M.H. Wissink"). Prose before the parties names
    no one, and more than ``KOP_MAX_PROSE_LINES`` lines of it end the search. ``None``
    when they name no one."""
    body = next(iter(_bodies(root)), None)
    if body is None:
        return None
    lines = (line for e in _line_elements(body) for line in _printed_lines(e))
    prose = 0
    for line in list(itertools.islice(lines, OPENING_LINES)):
        begin = _PARTIES_BEGIN.search(line)
        head = line[: begin.start()] if begin else line
        if len(head) <= PROSE_LINE_CHARS and (name := _name_in(head)):
            return name
        prose += len(line) > PROSE_LINE_CHARS
        if begin or prose > KOP_MAX_PROSE_LINES:
            return None
    return None


class _Sections:
    """The paragraphs of an ``<uitspraak>``, in reading order."""

    def __init__(self, kop: set[int]) -> None:
        self.entries: list[dict[str, Any]] = []  # named once all are read (_name)
        self._kop = kop  # the elements read into the kop

    def add(self, kind: str, number: str | None, text: str) -> None:
        # "6.16." as a list prints it: the number is 6.16
        number = number.rstrip(".") if number else number
        if not text and not number:
            return
        if number and not _slug(number):
            number = None
        self.entries.append({"number": number, "kind": kind, "text": text})

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
            elif name in ("uitspraak.info", "conclusie.info", "parablock"):
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
        own: list[ET.Element] = []
        for child in group:
            name = local_name(child.tag)
            if name in ("paragroup", "section"):
                self.flush(number, own, depth)
                (self.paragroup if name == "paragroup" else self.section)(child, depth)
            elif name not in _NOT_TEXT and id(child) not in self._kop:
                own.append(child)
        self.flush(number, own, depth)

    def flush(self, number: str, own: list[ET.Element], depth: int) -> None:
        """The own paragraphs of a numbered unit as one; a heading they end with ("faalt."
        and then "Slotsom" in italics) is a paragraph of its own after it."""
        texts = [
            (child, text) for child in own if (text := _unit_text(child, self._kop))
        ]
        own.clear()
        heading = None
        if len(texts) > 1 and _is_heading_line(texts[-1][0]):
            heading = texts.pop()[1]
        if texts:
            self.add(KIND_BODY, number, "\n\n".join(text for _, text in texts))
        if heading:
            self.add(KIND_HEADING if depth == 0 else KIND_SUBHEADING, None, heading)


# A heading a numbered unit ends with is no longer than this.
HEADING_LINE_CHARS = 80


def _is_heading_line(element: ET.Element) -> bool:
    """Is *element* a heading set as a paragraph: one short line, all of it in emphasis,
    that ends in no punctuation ("Slotsom" in italics)?"""
    paras = [p for p in iter_named(element, "para") if _flat(p)]
    if len(paras) != 1 or (paras[0].text or "").strip():
        return False
    children = list(paras[0])
    text = _flat(paras[0])
    return (
        bool(children)
        and all(
            local_name(c.tag) == "emphasis" and not (c.tail or "").strip()
            for c in children
        )
        and len(text) <= HEADING_LINE_CHARS
        and not text.endswith((".", ",", ";", ":", "?", "!", "”", '"'))
    )


def _unquote_headings(entries: list[dict[str, Any]]) -> None:
    """A run of numbered headings that goes back in the numbering, after which the
    numbering goes on where it was ("6", then "3 Proceskosten" and "4 Beslissing", then
    "7"): the headings of a decision the text quotes, whose sections the XML closes the
    text's own section with. They are text of the quote: a ``body`` paragraph, the number
    in front of its text. Numbering that starts again (1, 2, 1, 2, 3) is left as it is."""
    last = 0  # the last number of the text's own headings
    run: list[dict[str, Any]] = []
    for entry in entries:
        number = entry["number"] or ""
        if entry["kind"] != KIND_HEADING or not number.isdigit():
            continue
        if int(number) <= last:
            run.append(entry)
            continue
        if run and int(number) == last + 1 != int(run[-1]["number"]) + 1:
            for quoted in run:
                quoted["kind"] = KIND_BODY
                quoted["text"] = f"{quoted['number']} {quoted['text']}"
                quoted["number"] = None
        run, last = [], int(number)


# The signature of the Parket at the end of a conclusion: "De Procureur-Generaal bij de",
# "Hoge Raad der Nederlanden", "A-G" (or "Advocaat-Generaal", "Plv.").
_SIGNATURE_OPENS = re.compile(r"^de\s+procureur-generaal\b", re.IGNORECASE)
SIGNATURE_OPENING_CHARS = 80
SIGNATURE_LINE_CHARS = 40
SIGNATURE_MAX_LINES = 4


def _mark_signature(entries: list[dict[str, Any]]) -> None:
    """The closing lines of a conclusion that sign it: from the last short line that opens
    with "De Procureur-Generaal" to the end, when no more than ``SIGNATURE_MAX_LINES``
    short lines without a number follow it (a bold "AG" is read as a heading); kind
    ``signature``."""
    tail: list[dict[str, Any]] = []
    for entry in reversed(entries):
        text = entry["text"]
        if entry["number"]:
            return
        if len(text) <= SIGNATURE_OPENING_CHARS and _SIGNATURE_OPENS.match(text):
            for signed in [entry, *tail]:
                signed["kind"] = KIND_SIGNATURE
            return
        if len(text) > SIGNATURE_LINE_CHARS or len(tail) == SIGNATURE_MAX_LINES:
            return
        tail.append(entry)


def _name(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*entries* with their ``id`` (see ``extract_sections``)."""
    seen: dict[str, int] = {}
    named = []
    for position, entry in enumerate(entries, start=1):
        number = entry["number"]
        if number:
            base = f"{'rov' if entry['kind'] == KIND_BODY else 'kop'}-{_slug(number)}"
        else:
            base = f"p-{position}"
        seen[base] = seen.get(base, 0) + 1
        paragraph_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        named.append({"id": paragraph_id, **entry})
    return named


def extract_sections(root: ET.Element) -> list[dict[str, Any]]:
    """The paragraphs of the first ``<uitspraak>`` (or ``<conclusie>``): ``{id, number, kind,
    text}`` each.

    ``kind`` is ``heading`` (a section or a bridgehead), ``subheading`` (a nested one, or
    the kop), ``body`` or ``signature`` (the closing lines that sign a conclusion,
    ``_mark_signature``). The kop (``_read_kop``), when the judgment has one, is the first
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
    uitspraak = next(iter(_bodies(root)), None)
    if uitspraak is None:
        return []
    lines, kop = _read_kop(uitspraak)
    sections = _Sections(kop)
    sections.add(KIND_SUBHEADING, None, "\n\n".join(lines))
    sections.walk(uitspraak)
    _unquote_headings(sections.entries)
    _mark_signature(sections.entries)
    return _name(sections.entries)


# ── Atom index pages ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IndexEntry:
    """One judgment of a Rechtspraak index page."""

    ecli: str
    updated: dt.datetime | None  # when the judgment was published or last changed
    title: (
        str  # "ECLI:NL:RBROT:2021:207, Rechtbank Rotterdam, 15-01-2021, 8527084 VZ ..."
    )

    @property
    def case_numbers(self) -> str:
        """The case numbers at the end of the title, after the date; empty without."""
        match = _TITLE_CASE_NUMBERS.search(self.title)
        return match["numbers"].strip() if match else ""


# A court name can hold commas ("Gemeenschappelijk Hof van Justitie van Aruba, Curaçao, ...").
_TITLE_CASE_NUMBERS = re.compile(r",\s*\d{2}-\d{2}-\d{4},\s*(?P<numbers>.+)$")


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
