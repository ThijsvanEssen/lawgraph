"""The case numbers of a Rechtspraak judgment: as compared, as a translation writes them,
whether two name the same case, and the referring decisions a preliminary ruling names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lawgraph.core.dutch_dates import DATE, dutch_day
from lawgraph.core.ecli import cited_eclis, country_code
from lawgraph.core.xml import collapse_ws

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


# "19/00135 (Engels)", "C/09/456689 / HA ZA 13-1396 (English translation)": what a
# translation adds to the case number of the judgment it translates.
_TRANSLATION_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def translated_case_number(case_number: str | None) -> str | None:
    """The case number of the judgment a translation translates: its own without the
    closing remark in brackets. ``None`` when it has none."""
    if not case_number or not _TRANSLATION_SUFFIX.search(case_number):
        return None
    return _TRANSLATION_SUFFIX.sub("", case_number) or None


# ── the referral of a preliminary ruling ─────────────────────────────────────

# The paragraphs a ruling tells its referral in: the start ("1 De prejudiciële procedure"),
# after the parties and, when two courts asked, the procedure of each.
REFERRAL_PARAGRAPHS = 40
# "Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de
# rechtbank ... prejudiciële vragen aan de Hoge Raad gesteld"; "in de zaken 8674876/EJ VERZ
# 20-213 en 8675941 EJ VERZ 20-214 van 8 februari 2021"; "verwijst de Hoge Raad naar de
# beschikkingen in de zaak 4986381\EJ VERZ 16-142 en 5026511\EJ VERZ 16-163 van de
# kantonrechter te Enschede van 26 april 2016 en 20 mei 2016".
_CASE_THEN_DATE = re.compile(
    rf"\bin\s+de\s+za(?:ak|ken)\s+(?P<numbers>.{{3,160}}?)\s+van\s+(?P<date>{DATE})"
    rf"(?:\s+en\s+(?P<last>{DATE}))?",
    re.IGNORECASE,
)
# "Bij tussenvonnis van 14 november 2024 met zaaknummer C/15/351661 / KG ZA 24-199 heeft";
# "Bij tussenuitspraak van 28 april 2023, in zaak nr. 22/2463T, heeft".
_DATE_THEN_CASE = re.compile(
    rf"\bvan\s+(?P<date>{DATE}),?\s+(?:met\s+zaaknummers?|in\s+(?:de\s+)?zaak\s+nr\.?)"
    r"\s+(?P<numbers>.{3,120}?)\s*(?:,|\bheeft\b)",
    re.IGNORECASE,
)
# The criminal chamber, in its heading: "op de door de rechtbank Noord-Nederland bij
# beslissing van 19 december 2022, nummers 18-018510-21, 18-298097-21 en 18-298079-21,
# gestelde rechtsvragen".
_DECISION_NUMBERS = re.compile(
    rf"\bbij\s+beslissing\s+van\s+(?P<date>{DATE}),\s+(?:parket)?nummers?\s+"
    r"(?P<numbers>.{3,160}?),\s+gestelde\b",
    re.IGNORECASE,
)
_REFERRAL_FORMS = (_CASE_THEN_DATE, _DATE_THEN_CASE, _DECISION_NUMBERS)
# Where the case numbers of "in de zaak X van de rechtbank Y van <date>" end.
_COURT_AFTER_NUMBERS = re.compile(r"\s+van\s+(?:de|het)\s", re.IGNORECASE)


@dataclass(frozen=True)
class Referral:
    """What a preliminary ruling says of a decision that asked its questions."""

    eclis: tuple[str, ...] = ()
    case_numbers: tuple[str, ...] = ()  # as the text writes them
    date: str | None = None  # of the referring decision, ISO

    def names(self, case_number: str | None) -> bool:
        """Whether *case_number* (of a judgment, one or more) is one this referral names."""
        return any(same_case_number(own, case_number) for own in self.case_numbers)


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
    eclis = tuple(e for e in cited_eclis(text) if country_code(e) == "NL")
    if eclis:
        return Referral(eclis=eclis)
    match, numbers = _cases_and_date(text)
    if match and numbers:
        return Referral(case_numbers=numbers, date=dutch_day(match["date"]))
    if "laatstgenoemd" in lowered:
        return referred
    return None


def _referred_to(text: str) -> Referral | None:
    """The decision of the lower court a paragraph points to, at the last of its dates."""
    match, numbers = _cases_and_date(text)
    if match is None or not numbers:
        return None
    last = match.groupdict().get("last") or match["date"]
    return Referral(case_numbers=numbers, date=dutch_day(last))


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
