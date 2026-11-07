"""What a criminal judgment decided on the charge, as ``judgment.criminal_decision`` gives it."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.criminal_decision import CriminalGap, Proven, SentenceKind

_GAP = (
    "Why it is empty: `geen-dictum` (no decision read in the text), `geen-strafvonnis` "
    "(the decision neither proves nor sentences: a complaint, a confiscation order, an "
    "appeal court that confirms), `niet-in-dictum` (the decision sentences but does not "
    "say what was proven: an appeal court that changes only the sentence), "
    "`niet-gevonden` (proven, but no main sentence read: the decision may be cut off or "
    "impose a measure alone; never read it as no sentence), `vrijgesproken` (nothing "
    "proven); null when it is not empty."
)


class CriminalSentenceDTO(StrictModel):
    """A main punishment as the decision imposes it."""

    kind: SentenceKind = Field(
        description="`gevangenisstraf`, `taakstraf`, `geldboete`, `jeugddetentie`, "
        "`hechtenis`, `tbs`, or `meerdere` for one clause that imposes more than one."
    )
    text: str = Field(
        description="The clause as the decision writes it, at most 240 characters: "
        '"Veroordeelt verdachte tot een gevangenisstraf voor de duur van 3 (drie) jaren." '
        "Its duration or amount is text, not a number to sort on."
    )


class CriminalDecisionDTO(StrictModel):
    """What a criminal judgment of a rechtbank or gerechtshof decided on the charge, read
    from its decision (``core/criminal_decision.py``). It is the outcome of the whole case,
    not of one article it cites: with more than one charge, `deels` says nothing of one."""

    proven: Proven | None = Field(
        description="`ja` (verklaart bewezen), `deels` (a charge proven, another acquitted "
        "or the prosecution inadmissible for it), `nee` (acquitted of all); null with "
        "`proven_missing`."
    )
    proven_missing: CriminalGap | None = Field(description=_GAP)
    sentences: list[CriminalSentenceDTO] = Field(
        description="The main punishments the decision imposes, in its order; empty with "
        "`sentences_missing`."
    )
    sentences_missing: CriminalGap | None = Field(description=_GAP)


class CriminalFields(StrictModel):
    """The ``criminal_decision`` of a judgment."""

    criminal_decision: CriminalDecisionDTO | None = Field(
        default=None,
        description="Of a criminal judgment of a rechtbank or gerechtshof (no conclusion), "
        "what it decided on the charge; null for any other (the Hoge Raad rules on the "
        "cassation appeal, not on the charge) and for one `normalize rechtspraak` has not "
        "read since.",
    )


def criminal_decision(props: dict[str, Any]) -> CriminalDecisionDTO | None:
    """The ``criminal_decision`` of a judgment with these props."""
    found = props.get("criminal_decision")
    return CriminalDecisionDTO(**found) if found else None
