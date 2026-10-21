"""Where an edge comes from: every value a pipeline writes in ``meta.basis``,
``meta.bases`` or ``meta.reason``, and what it means.

``tests/test_provenance.py`` holds the pipelines to it: a value that is not in
``PROVENANCE`` is not written. The table in ``docs/data-model.md`` between the
``provenance:begin`` and ``provenance:end`` markers is generated from this module::

    python -m lawgraph.core.provenance
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Final, Literal

from lawgraph.config.constants import (
    CHANGE_RELATIONS,
    IMPLEMENTS_BASIS_CONSIDERANS,
    IMPLEMENTS_BASIS_NIM,
    RELATION_ABOUT,
    RELATION_ADVISES_ON,
    RELATION_ANSWERS,
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_IMPLEMENTS,
    RELATION_MADE_IN,
    RELATION_REFERRED_BY,
    RELATION_REFERS_TO,
    RELATION_RELATED_TO,
    RELATION_SAME_AS,
    RELATION_TRANSPOSED_TO,
)

Basis = Literal[
    "formal_relation",
    "later_instance",
    "appeal_text",
    "case_number",
    "referral_text",
    "national_decision",
    "summary_text",
    "is_replaced_by",
    "appno_and_date",
    "official_id",
    "birth_date_surname_initials",
    "subject",
    "text",
    "footnote",
    "transposition_table",
    "nakoming",
    "agenda",
]
Reason = Literal[
    "bwb_article",
    "celex_article",
    "bwb_instrument",
    "celex_instrument",
    "unknown",
    "bwb_xml_ref",
    "amendment_text",
    "ingediend",
    "verplaatst",
]

BASIS_FORMAL: Final[Basis] = "formal_relation"
BASIS_LATER_INSTANCE: Final[Basis] = "later_instance"
BASIS_APPEAL_TEXT: Final[Basis] = "appeal_text"
BASIS_CASE_NUMBER: Final[Basis] = "case_number"
BASIS_REFERRAL_TEXT: Final[Basis] = "referral_text"
BASIS_NATIONAL_DECISION: Final[Basis] = "national_decision"
BASIS_SUMMARY_TEXT: Final[Basis] = "summary_text"
BASIS_REPLACED_BY: Final[Basis] = "is_replaced_by"
BASIS_APPNO_AND_DATE: Final[Basis] = "appno_and_date"
BASIS_OFFICIAL_ID: Final[Basis] = "official_id"
BASIS_SAME_PERSON: Final[Basis] = "birth_date_surname_initials"
BASIS_SUBJECT: Final[Basis] = "subject"
BASIS_TEXT: Final[Basis] = "text"
BASIS_FOOTNOTE: Final[Basis] = "footnote"
BASIS_TRANSPOSITION_TABLE: Final[Basis] = "transposition_table"
BASIS_FULFILMENT: Final[Basis] = "nakoming"
BASIS_AGENDA: Final[Basis] = "agenda"

REASON_BWB_ARTICLE: Final[Reason] = "bwb_article"
REASON_CELEX_ARTICLE: Final[Reason] = "celex_article"
REASON_BWB_INSTRUMENT: Final[Reason] = "bwb_instrument"
REASON_CELEX_INSTRUMENT: Final[Reason] = "celex_instrument"
REASON_UNKNOWN: Final[Reason] = "unknown"
REASON_XML_REF: Final[Reason] = "bwb_xml_ref"
REASON_AMENDMENT_TEXT: Final[Reason] = "amendment_text"
REASON_SUBMITTED: Final[Reason] = "ingediend"
REASON_MOVED: Final[Reason] = "verplaatst"

Field = Literal["basis", "bases", "reason"]


@dataclass(frozen=True)
class Provenance:
    field: Field  # the key of ``meta`` that holds the value
    value: str
    relations: tuple[str, ...]  # the relations whose edges carry it
    meaning: str


PROVENANCE: tuple[Provenance, ...] = (
    Provenance(
        "basis",
        BASIS_FORMAL,
        (
            RELATION_APPEAL_OF,
            RELATION_CONTINUES,
            RELATION_REFERRED_BY,
            RELATION_ADVISES_ON,
            RELATION_ANSWERS,
        ),
        "The metadata of the judgment names the other (`dcterms:relation`).",
    ),
    Provenance(
        "basis",
        BASIS_LATER_INSTANCE,
        (RELATION_APPEAL_OF, RELATION_CONTINUES, RELATION_REFERRED_BY),
        "The metadata of the earlier judgment names the later one.",
    ),
    Provenance(
        "basis",
        BASIS_APPEAL_TEXT,
        (RELATION_APPEAL_OF,),
        "The text says which decision it appeals, by date and case number.",
    ),
    Provenance(
        "basis",
        BASIS_CASE_NUMBER,
        (RELATION_ADVISES_ON,),
        "The conclusion and the judgment share a case number.",
    ),
    Provenance(
        "basis",
        BASIS_REFERRAL_TEXT,
        (RELATION_ANSWERS,),
        "The text of the preliminary ruling names the referring decision: its ECLI, or "
        "its case number and date.",
    ),
    Provenance(
        "basis",
        BASIS_NATIONAL_DECISION,
        (RELATION_ANSWERS,),
        "CELLAR names the national decision that referred the questions to the Court of "
        "Justice (`case-law_national-judgement`): its ECLI, or its date and case number.",
    ),
    Provenance(
        "basis",
        BASIS_SUMMARY_TEXT,
        (RELATION_RELATED_TO,),
        "The summary names the other as a connected case (`meta.text`).",
    ),
    Provenance(
        "basis",
        BASIS_REPLACED_BY,
        (RELATION_SAME_AS,),
        "The metadata names the publication that replaces it (`dcterms:isReplacedBy`).",
    ),
    Provenance(
        "basis",
        BASIS_APPNO_AND_DATE,
        (RELATION_SAME_AS,),
        "Two language versions of an ECHR decision: the same application numbers and "
        "date.",
    ),
    Provenance(
        "basis",
        BASIS_OFFICIAL_ID,
        (RELATION_SAME_AS,),
        "A publication of the Staatsblad or Staatscourant and the BWB publication of the "
        "same official id.",
    ),
    Provenance(
        "basis",
        BASIS_SAME_PERSON,
        (RELATION_SAME_AS,),
        "A bare `Persoon` of the Tweede Kamer and a member with the same birth date, "
        "surname and initials.",
    ),
    Provenance(
        "basis",
        BASIS_SUBJECT,
        (RELATION_ANSWERS, RELATION_REFERS_TO),
        "The subject of the Kamerstuk names the paper by dossier and number.",
    ),
    Provenance(
        "basis",
        BASIS_TEXT,
        (RELATION_ANSWERS,),
        "A line of the text of the letter names the motion.",
    ),
    Provenance(
        "basis",
        BASIS_FOOTNOTE,
        (RELATION_ANSWERS,),
        "A footnote of the letter names the motion.",
    ),
    Provenance(
        "basis",
        BASIS_TRANSPOSITION_TABLE,
        (RELATION_TRANSPOSED_TO,),
        "The table of the recodification places the old article in the new law (the "
        "transposition table sent with the bill, a bijlage of its memorie van toelichting "
        "or a table in it; the concordance table of an EU act that codifies or recasts "
        "others), and the text of the new law holds that article and lid.",
    ),
    Provenance(
        "basis",
        BASIS_FULFILMENT,
        (RELATION_ABOUT,),
        "A commitment and the dossier of the letter that fulfils it "
        "(`Toezegging.KamerbriefNakoming`, its `Kamerstukdossier`): the dossier the Kamer "
        "files its answer in.",
    ),
    Provenance(
        "basis",
        BASIS_AGENDA,
        (RELATION_ABOUT,),
        "A commitment no letter in a stored dossier fulfils, and a dossier on the agenda "
        "of the debate it was made in: discussed there, not necessarily its subject.",
    ),
    Provenance(
        "bases",
        IMPLEMENTS_BASIS_NIM,
        (RELATION_IMPLEMENTS,),
        "EUR-Lex lists the publication as a national implementing measure of the act.",
    ),
    Provenance(
        "bases",
        IMPLEMENTS_BASIS_CONSIDERANS,
        (RELATION_IMPLEMENTS,),
        "The considerans of the regulation says it implements the act.",
    ),
    Provenance(
        "reason",
        REASON_BWB_ARTICLE,
        (RELATION_REFERS_TO,),
        "The text cites an article of a law (BWB).",
    ),
    Provenance(
        "reason",
        REASON_CELEX_ARTICLE,
        (RELATION_REFERS_TO,),
        "The text cites an article of an EU act.",
    ),
    Provenance(
        "reason",
        REASON_BWB_INSTRUMENT,
        (RELATION_REFERS_TO,),
        "The text cites a law (BWB) as a whole.",
    ),
    Provenance(
        "reason",
        REASON_CELEX_INSTRUMENT,
        (RELATION_REFERS_TO,),
        "The text cites an EU act as a whole.",
    ),
    Provenance(
        "reason",
        REASON_UNKNOWN,
        (RELATION_REFERS_TO,),
        "A citation that names neither a law nor an EU act.",
    ),
    Provenance(
        "reason",
        REASON_XML_REF,
        (RELATION_REFERS_TO,),
        "A reference the BWB XML of the article records (`intref`, `extref`).",
    ),
    Provenance(
        "reason",
        REASON_AMENDMENT_TEXT,
        CHANGE_RELATIONS,
        "The text of the amendment names the article it changes (`meta.snippet`).",
    ),
    Provenance(
        "reason",
        REASON_SUBMITTED,
        (RELATION_MADE_IN,),
        "The motion was submitted in the debate held on the day its case started.",
    ),
    Provenance(
        "reason",
        REASON_MOVED,
        (RELATION_CONTINUES,),
        "The activity replaced a moved one (`Activiteit.VervangenDoor`).",
    ),
)

BLOCK_BEGIN = (
    "<!-- provenance:begin (generated: python -m lawgraph.core.provenance) -->"
)
BLOCK_END = "<!-- provenance:end -->"


def render_table() -> str:
    """The Markdown table of ``PROVENANCE``."""
    lines = [
        "| Meta | Value | Relations | Meaning |",
        "|------|-------|-----------|---------|",
    ]
    lines += [
        f"| `{p.field}` | `{p.value}` | {', '.join(f'`{r}`' for r in p.relations)} "
        f"| {p.meaning} |"
        for p in PROVENANCE
    ]
    return "\n".join(lines) + "\n"


def replace_block(document: str) -> str:
    """*document* with the generated block between the markers refreshed."""
    head, _, rest = document.partition(BLOCK_BEGIN)
    _, _, tail = rest.partition(BLOCK_END)
    return f"{head}{BLOCK_BEGIN}\n\n{render_table()}\n{BLOCK_END}{tail}"


def block_of(document: str) -> str:
    """The generated block now in *document* (markers excluded)."""
    _, _, rest = document.partition(BLOCK_BEGIN)
    body, _, _ = rest.partition(BLOCK_END)
    return body.strip() + "\n"


if __name__ == "__main__":
    path = pathlib.Path(__file__).resolve().parents[3] / "docs" / "data-model.md"
    path.write_text(replace_block(path.read_text()))
