"""Decision (vote) responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import DossierNameDTO, dossier_names_of
from lawgraph.core.documents import chamber_of

_KIND = (
    "What was decided on: the ``Zaak.Soort`` of the case it decided (``primary_case_kind``), "
    "or the one Soort of the cases on its agenda item, as the Kamer writes it: ``Motie``, "
    "``Amendement``, ``Wetgeving``, ``Begroting``, ...; null when neither tells."
)
_EK = (
    "Of a vote of the Eerste Kamer (``chamber`` ``EK``), as eerstekamer.nl writes it; null "
    "for the Tweede Kamer."
)
_RESULT = "The outcome the Eerste Kamer shows: ``Aangenomen``, ``Verworpen``. " + _EK
_METHOD = (
    "How it was decided, as the report names it: ``Hamerstuk``, ``Stemming bij zitten en "
    "opstaan, aangenomen``, ``Hoofdelijke stemming, verworpen``. " + _EK
)
_BILL_DECISION = (
    "Whether it is the vote that decided the bill: the list of the Eerste Kamer names a "
    "vote on a motion by its bill too. " + _EK
)
_DECISION_KIND = (
    "``BesluitSoort`` as the Kamer writes it: ``Stemmen - aangenomen``, ``Stemmen - "
    "verworpen``, ``Stemmen - zonder stemming aannemen`` (a hamerstuk: no votes), "
    "``Stemmen - uitstellen``, ..."
)


class VoteDTO(BaseModel):
    """One vote cast on a decision, by a faction or — on a roll-call — a member."""

    model_config = ConfigDict(extra="forbid")

    voter_id: str = Field(..., description="Arango _id of the member or faction.")
    voter_key: str
    name: str | None = None
    choice: str = Field(
        ..., description="The vote as the source wrote it: Voor, Tegen, Onthouden, …"
    )
    seats: int = 0


class DecisionDTO(BaseModel):
    """One decision with every vote cast on it.

    ``vote_kind`` says who the votes come from: ``member`` for a roll-call
    (``hoofdelijke stemming``), ``faction`` otherwise. ``tally`` is seats per
    choice — members per choice on a roll-call — and ``voters`` is how many
    cast each choice.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    date: str | None = None
    subject: str | None = None
    external_id: str | None = Field(None, description="TK Besluit identifier.")
    passed: bool | None = Field(
        None,
        description="Whether it carried; null for a decision that is no vote "
        "(``Stemmen - uitstellen``).",
    )
    kind: str | None = Field(None, description=_KIND)
    decision_kind: str | None = Field(None, description=_DECISION_KIND)
    primary_case_kind: str | None = Field(
        None,
        description="The ``Zaak.Soort`` of the case it decided: ``Wetgeving`` on the vote on "
        "a bill itself, ``Amendement`` or ``Motie`` on the others.",
    )
    dossier_numbers: list[str] = Field(
        default_factory=list,
        description="The dossiers of the cases it decided (``36774``, ``37020-XV``).",
    )
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers``, in their order: ``number``, "
        "``short_title``, ``title`` as ``/api/dossiers`` gives them.",
    )
    chamber: str | None = Field(None, description="'TK' or 'EK'.")
    result: str | None = Field(None, description=_RESULT)
    method: str | None = Field(None, description=_METHOD)
    bill_decision: bool | None = Field(None, description=_BILL_DECISION)
    factions_for: list[str] = Field(default_factory=list, description=_EK)
    factions_against: list[str] = Field(default_factory=list, description=_EK)
    factions_noted: list[str] = Field(
        default_factory=list,
        description="The factions that asked to have their vote recorded. " + _EK,
    )
    bill_url: str | None = Field(None, description=_EK)
    source_url: str | None = Field(
        None, description="The part of the report of the meeting. " + _EK
    )
    retrieved_on: str | None = Field(None, description=_EK)
    vote_kind: str | None = Field(
        None, description="``member``, ``faction``; null without votes (a hamerstuk)."
    )
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)
    votes: list[VoteDTO] = Field(default_factory=list)

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], names: dict[str, dict[str, Any]]
    ) -> DecisionDTO:
        """From the stored decision with its votes, and the names of the dossiers
        (``load_dossier_names``)."""
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            date=props.get("date"),
            subject=props.get("subject"),
            external_id=props.get("decision_id"),
            passed=props.get("passed"),
            kind=props.get("kind"),
            decision_kind=props.get("decision_kind"),
            primary_case_kind=props.get("primary_case_kind"),
            dossier_numbers=props.get("dossier_numbers") or [],
            dossiers=dossier_names_of(props.get("dossier_numbers") or [], names),
            chamber=props.get("chamber") or chamber_of(doc.get("labels")),
            result=props.get("result"),
            method=props.get("method"),
            bill_decision=props.get("bill_decision"),
            factions_for=props.get("factions_for") or [],
            factions_against=props.get("factions_against") or [],
            factions_noted=props.get("factions_noted") or [],
            bill_url=props.get("bill_url"),
            source_url=props.get("source_url"),
            retrieved_on=props.get("retrieved_on"),
            vote_kind=props.get("vote_kind"),
            tally=props.get("tally") or {},
            voters=props.get("voters") or {},
            votes=[VoteDTO(**v) for v in doc.get("votes") or []],
        )


class DecisionSummaryDTO(BaseModel):
    """One row in the decision browser.

    ``tally`` sums the seats behind each choice — the number to show for a
    result — and ``voters`` counts how many factions (or members) made it.
    ``subject`` is that of the case the vote decided; a vote without a case of its own
    on an agenda item of several shares the item's subject with its siblings, and
    ``display_name`` (``Motie 2024Z17945: …``) and ``external_id`` tell them apart.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    date: str | None = None
    subject: str | None = None
    display_name: str | None = Field(
        None,
        description="The heading of the vote, distinct per sibling on an agenda item: "
        "``Motie 2024Z17945: <subject>``, the subject alone when it names its kind.",
    )
    external_id: str | None = None
    dossier_numbers: list[str] = Field(default_factory=list)
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers``, in their order: ``number``, "
        "``short_title``, ``title`` as ``/api/dossiers`` gives them.",
    )
    kind: str | None = Field(None, description=_KIND)
    primary_case_kind: str | None = Field(
        None,
        description="The ``Zaak.Soort`` of the case the vote singled out (``Motie``, "
        "``Amendement``, ``Wetgeving``); null when it singled out none.",
    )
    decision_kind: str | None = Field(None, description=_DECISION_KIND)
    passed: bool | None = None
    chamber: str | None = None
    result: str | None = Field(None, description=_RESULT)
    method: str | None = Field(None, description=_METHOD)
    bill_decision: bool | None = Field(None, description=_BILL_DECISION)
    vote_kind: str | None = None
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)


class DecisionKindCount(BaseModel):
    """How many of the decisions are of one kind, and how many of those carried and did
    not (the rest have no outcome)."""

    model_config = ConfigDict(extra="forbid")

    value: str | None
    count: int
    passed: int = 0
    rejected: int = 0


class DecisionOutcomeCount(BaseModel):
    """How many of the decisions carried (``true``), did not, or have no outcome (null)."""

    model_config = ConfigDict(extra="forbid")

    value: bool | None
    count: int


class DecisionDayCount(BaseModel):
    """The decisions of one day: how many, and how many of them carried."""

    model_config = ConfigDict(extra="forbid")

    date: str | None
    count: int
    passed: int


class DecisionYearCount(BaseModel):
    """The decisions of one year: how many, how many carried, how many did not."""

    model_config = ConfigDict(extra="forbid")

    year: str | None
    count: int
    passed: int
    rejected: int


class PartyVoteCount(BaseModel):
    """How a faction voted on some of the decisions: ``voor``, ``tegen``, and ``none``
    (another choice, or no vote of the faction: a roll-call vote is one of members)."""

    model_config = ConfigDict(extra="forbid")

    voor: int
    tegen: int
    none: int


class PartyVoteKindCount(PartyVoteCount):
    value: str | None = Field(None, description="The kind, as in ``kind``.")


class PartyVoteYearCount(PartyVoteCount):
    year: str | None = None


class PartyVotes(PartyVoteCount):
    """How one faction voted on the decisions under every filter: in all, per kind (most
    decisions first) and per year (oldest first)."""

    party: str = Field(..., description="The key of the faction.")
    name: str | None = Field(None, description="Its abbreviation, else its name.")
    kind: list[PartyVoteKindCount] = Field(default_factory=list)
    years: list[PartyVoteYearCount] = Field(default_factory=list)


class DecisionFacets(BaseModel):
    """The decisions under the filters, counted.

    ``kind`` is counted without the ``kind`` filter and ``passed`` without the ``passed``
    filter, so each shows what choosing another value would give; ``days`` is counted
    under every filter.
    """

    model_config = ConfigDict(extra="forbid")

    kind: list[DecisionKindCount] = Field(
        default_factory=list, description="Per kind, most first."
    )
    passed: list[DecisionOutcomeCount] = Field(
        default_factory=list, description="Per outcome, most first."
    )
    days: list[DecisionDayCount] = Field(
        default_factory=list, description="Per date of the vote, oldest first."
    )
    years: list[DecisionYearCount] = Field(
        default_factory=list, description="Per year of the vote, oldest first."
    )
    party_votes: list[PartyVotes] = Field(
        default_factory=list,
        description="With ``party_votes``: per faction asked, by key, how it voted.",
    )


class DecisionListResponse(BaseModel):
    """A page of decisions."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Matching decisions, independent of ``limit``.")
    items: list[DecisionSummaryDTO]
    facets: DecisionFacets = Field(default_factory=DecisionFacets)
    partial: bool = Field(
        False,
        description="``party_votes`` was asked for but is still being counted (every vote "
        "on every decision: seconds, once per change of the data): ``[]`` now; ask again.",
    )
