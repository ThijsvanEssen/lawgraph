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

# The tier of a judgment is the college that gave it, as the Rechtspraak itself sorts its
# instanties (the ``Type`` of each in its waardelijst ``/Waardelijst/Instanties``): a highest
# court on its own, the courts of one kind together, every other college under its own name.
# ``tests/fixtures/rechtspraak_instanties.xml`` holds that list; a test fails when one of its
# codes has no tier here. ``graph-list-stats`` writes the same in AQL from these tables.
TIER_HOGE_RAAD = "hoge_raad"
TIER_RAAD_VAN_STATE = "raad_van_state"
TIER_CENTRALE_RAAD = "centrale_raad_van_beroep"
TIER_CBB = "college_van_beroep_bedrijfsleven"
# The Parket bij de Hoge Raad: the conclusions of its advocates-general, no judgments.
TIER_PARKET = "parket"
TIER_GERECHTSHOF = "gerechtshof"
TIER_RECHTBANK = "rechtbank"
TIER_KANTONGERECHT = "kantongerecht"  # until 2002
TIER_TUCHTCOLLEGE = (
    "tuchtcollege"  # every disciplinary tribunal (tuchtrechtelijke instantie)
)
TIER_EHRM = (
    "ehrm"  # the European Court of Human Rights (source ``echr``); no Dutch court
)
TIER_KROON = "kroon"  # a decision of the Crown on an appeal (Kroonberoep, court "KB")
TIER_HVJ_EU = "hvj_eu"  # the Court of Justice of the European Union

TIER_OF_COURT = {
    "HR": TIER_HOGE_RAAD,
    "RVS": TIER_RAAD_VAN_STATE,
    "CRVB": TIER_CENTRALE_RAAD,
    "CBB": TIER_CBB,
    "PHR": TIER_PARKET,
    "CBHO": "college_van_beroep_hoger_onderwijs",
    "CVBSTUF": "college_van_beroep_studiefinanciering",
    "DETARCO": "tariefcommissie",
    "RSJ": "raad_voor_strafrechtstoepassing_en_jeugdbescherming",
    "RVAB": "raad_van_arbitrage_in_bouwgeschillen",
    "OCHM": "constitutioneel_hof",
    "OHJNA": "gemeenschappelijk_hof",  # the Hof van Justitie before the Gemeenschappelijk Hof
    "IAR": TIER_TUCHTCOLLEGE,
    "XX": "buitenlandse_instantie",  # the waardelijst: a court outside the Netherlands
    "ECHR": TIER_EHRM,
}
# The kind of court a code starts with; the longest prefix wins.
TIER_OF_PREFIX = {
    "GH": TIER_GERECHTSHOF,
    "RB": TIER_RECHTBANK,
    "KTG": TIER_KANTONGERECHT,
    "T": TIER_TUCHTCOLLEGE,
    "AG": "ambtenarengerecht",
    "RVB": "raad_van_beroep",  # the raden van beroep in social security, until 1992
    "OGH": "gemeenschappelijk_hof",
    "OGEA": "gerecht_in_eerste_aanleg",
    "OGA": "gerecht_in_ambtenarenzaken",
    "ORBA": "raad_van_beroep_in_ambtenarenzaken",
    "ORBB": "raad_van_beroep_voor_belastingzaken",
}
PREFIX_LENGTHS = sorted({len(p) for p in TIER_OF_PREFIX}, reverse=True)
# An ECLI of the code XX ("another issuer": the waardelijst calls it the foreign courts) is
# published by the Rechtspraak for courts outside it; the court names which.
TIER_OF_OTHER_COURT = {
    "KB": TIER_KROON,
    "Europees Hof voor de Rechten van de Mens": TIER_EHRM,
    "Hof van Justitie van de Europese Unie": TIER_HVJ_EU,
    "Hof van Justitie van de Europese Gemeenschappen": TIER_HVJ_EU,
}

# In the order lists show them: the highest courts, the parket, the courts of first instance
# and appeal, then the other colleges, the Caribbean part, the EHRM last.
TIERS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            TIER_HOGE_RAAD,
            TIER_RAAD_VAN_STATE,
            TIER_CENTRALE_RAAD,
            TIER_CBB,
            TIER_PARKET,
            TIER_GERECHTSHOF,
            TIER_RECHTBANK,
            TIER_KANTONGERECHT,
            TIER_TUCHTCOLLEGE,
            *sorted(
                {*TIER_OF_COURT.values(), *TIER_OF_PREFIX.values()}
                - {TIER_EHRM, "buitenlandse_instantie"}
            ),
            TIER_KROON,
            "buitenlandse_instantie",
            TIER_HVJ_EU,
            TIER_EHRM,
        ]
    )
)


def court_tier(court_code: str | None, court: str | None = None) -> str | None:
    """The tier of a court: its code (``TIER_OF_COURT``), else the longest prefix of the code
    (``TIER_OF_PREFIX``); for code ``XX`` the court it names (``TIER_OF_OTHER_COURT``). ``None``
    for no code, or a code no table knows: never a catch-all."""
    if not court_code:
        return None
    if court_code == "XX" and (court or "").strip() in TIER_OF_OTHER_COURT:
        return TIER_OF_OTHER_COURT[(court or "").strip()]
    if court_code in TIER_OF_COURT:
        return TIER_OF_COURT[court_code]
    return next(
        (
            TIER_OF_PREFIX[court_code[:length]]
            for length in PREFIX_LENGTHS
            if court_code[:length] in TIER_OF_PREFIX
        ),
        None,
    )


def derive_court_tier(
    ecli: str | None, court: str | None = None
) -> tuple[str | None, str | None]:
    """Return ``(court_code, tier)`` derived from the ECLI identifier and the court."""
    if not ecli:
        return None, None
    parts = ecli.split(":")
    court_code = parts[2].upper() if len(parts) >= 3 else None
    return court_code, court_tier(court_code, court)


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
