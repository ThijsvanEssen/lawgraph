"""What an earlier judgment of a case is to a later one, and the decision an appeal says it
appeals (pure: no I/O, no store).

The metadata of a judgment names its earlier instances (``dcterms:relation``,
``props.related_eclis``) without saying what they are to it. Most are the decision appealed;
two are not: an earlier judgment of the same court in the same case (an interim judgment,
then the final one), and the ruling of the Hoge Raad that set aside a decision and sent the
case to the court that decided again (verwijzing).

An appeal whose metadata names none often says in its kop which decision it appeals: "tegen
de uitspraak van de rechtbank Gelderland van 9 juli 2025 in zaak nr. 24/6811".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
)
from lawgraph.core.judgments import (
    PROCEDURE_PRELIMINARY_RULING,
    _dutch_date,
    same_case_number,
)
from lawgraph.core.xml import collapse_ws

# The court that refers a case to another after setting aside its decision.
CASSATION_COURT = "HR"
# The procedures of a judgment on appeal, in cassation or after referral
# (``judgment_metadata.type``: "Hoger beroep", "Cassatie", "Verwijzing na Hoge Raad", and the
# cassation the Hoge Raad decides briefly, "Artikel 80a RO-zaken", "Artikel 81 RO-zaken").
APPEAL_PROCEDURE = re.compile(
    r"\b(?:hoger beroep|cassatie|verwijzing|artikel 8(?:0a|1) ro)\b", re.IGNORECASE
)


def court_of(ecli: str) -> str:
    """The court code of an ECLI: ``HR`` of ``ECLI:NL:HR:2019:1858``."""
    parts = ecli.upper().split(":")
    return parts[2] if len(parts) > 2 else ""


@dataclass(frozen=True)
class Instance:
    """What is known of one judgment of a case; of a stub only its ECLI."""

    ecli: str
    case_number: str | None = None
    case_number_keys: tuple[str, ...] = ()
    procedure: str | None = None
    is_conclusion: bool = False
    date: str | None = None

    @classmethod
    def of(cls, row: dict[str, Any]) -> Instance:
        return cls(
            ecli=str(row["ecli"]).upper(),
            case_number=row.get("case_number"),
            case_number_keys=tuple(row.get("case_number_keys") or ()),
            procedure=row.get("procedure"),
            is_conclusion=bool(row.get("is_conclusion")),
            date=row.get("date"),
        )

    def same_case(self, other: Instance) -> bool:
        """Whether the two share a case number (``core.judgments.same_case_number``)."""
        if set(self.case_number_keys) & set(other.case_number_keys):
            return True
        return bool(
            self.case_number
            and other.case_number
            and same_case_number(other.case_number, self.case_number)
        )


def earlier_instance_relation(later: Instance, earlier: Instance) -> str | None:
    """The edge from *later* to an earlier instance its metadata names, or ``None``.

    The same court in the same case: ``CONTINUES``. A ruling of the Hoge Raad named by
    another court: ``REFERRED_BY`` (the case came back to it after cassation); a preliminary
    ruling the court asked for is none (``ANSWERS`` ties the two the other way). A conclusion
    is none (``ADVISES_ON``), and so is a judgment given after *later*: a later instance the
    metadata does not call one. Any other: ``APPEAL_OF``.
    """
    if earlier.is_conclusion:
        return None
    if later.date and earlier.date and earlier.date > later.date:
        return None
    same_court = court_of(later.ecli) == court_of(earlier.ecli)
    if same_court and later.same_case(earlier):
        return RELATION_CONTINUES
    if court_of(earlier.ecli) == CASSATION_COURT and not same_court:
        if earlier.procedure == PROCEDURE_PRELIMINARY_RULING:
            return None
        return RELATION_REFERRED_BY
    return RELATION_APPEAL_OF


# ── the decision an appeal names in its text ─────────────────────────────────

# The paragraphs an appeal names the decision it appeals in: the kop and the procedure.
APPEAL_TARGET_PARAGRAPHS = 12
_DATE = r"\d{1,2}\s+[a-z]+\s+\d{4}"
# "tegen de uitspraak van de rechtbank Gelderland van 9 juli 2025 in zaak nr. 24/6811";
# "tegen het vonnis van de rechtbank te Rotterdam van 12 december 2002 in de strafzaak onder
# parketnummer 10/123456-01"; "tegen een arrest van het gerechtshof Den Haag van 2 februari
# 2021, nummer 22-001234-20"; "tegen de beslissing van de kantonrechter van de rechtbank
# Rotterdam van 5 april 2011".
_APPEALED = re.compile(
    r"\btegen\s+(?:de|het|een)\s+"
    r"(?:uitspraak|vonnis|beschikking|beslissing|arrest|tussenuitspraak|einduitspraak)\s+"
    rf"van\s+(?P<court>(?:de|het)\s+.{{3,80}}?)\s+van\s+(?P<date>{_DATE})"
    r"(?:,?\s+(?:in\s+(?:de\s+)?(?:straf)?zaak\s+)?(?:onder\s+|met\s+)?"
    r"(?:(?:zaak|parket|rol|registratie)?nummers?|nrs?\.|nr|kenmerk|reg\.\s*nrs?\.)"
    r"\s*:?\s*(?P<number>(?:[A-Z]{1,6}\s)?[A-Z]{0,3}\d[\w./-]*\d[A-Z]{0,4}))?",
    re.IGNORECASE,
)
# What the court is: not an administrative body ("het college van burgemeester en
# wethouders"), whose decision an appeal to a court is not an appeal of.
_COURT_WORD = re.compile(
    r"\b(?:rechtbank|arrondissementsrechtbank|rechter|kantonrechter|voorzieningenrechter|"
    r"politierechter|kinderrechter|kantongerecht|gerechtshof|hof|gerecht|"
    r"centrale\s+raad|college\s+van\s+beroep|raad\s+van\s+state|tuchtcollege)\b",
    re.IGNORECASE,
)
_ARTICLE = re.compile(r"^(?:de|het)\s+", re.IGNORECASE)
# A soft hyphen where the text breaks a name: "Noord\u00ad-Nederland", "Midden\u00adNederland".
_SOFT_HYPHEN = re.compile("\u00ad-?")


@dataclass(frozen=True)
class AppealTarget:
    """The decision an appeal names in its text: the court as written, the date, the case
    number when the text gives one."""

    court: str
    date: str  # ISO
    case_number: str | None = None

    def as_props(self) -> dict[str, str | None]:
        return {"court": self.court, "date": self.date, "case_number": self.case_number}

    def is_decision(self, row: dict[str, Any]) -> bool:
        """Whether *row* (``{date, case_number}`` of a judgment) is this decision."""
        return bool(
            self.case_number
            and row.get("date") == self.date
            and same_case_number(self.case_number, row.get("case_number"))
        )


def read_appeal_targets(paragraphs: list[dict[str, Any]]) -> list[AppealTarget]:
    """The decisions an appeal says it appeals, from the first paragraph that names one
    ("tegen de uitspraak van de rechtbank ... van <date> [in zaak nr. <number>]")."""
    for paragraph in paragraphs[:APPEAL_TARGET_PARAGRAPHS]:
        text = collapse_ws(paragraph.get("text") or "")
        targets: list[AppealTarget] = []
        for match in _APPEALED.finditer(text):
            court = _SOFT_HYPHEN.sub("-", _ARTICLE.sub("", match["court"])).rstrip(" ,")
            date = _dutch_date(match["date"])
            if not date or not _COURT_WORD.search(court):
                continue
            target = AppealTarget(court=court, date=date, case_number=match["number"])
            if target not in targets:
                targets.append(target)
        if targets:
            return targets
    return []
