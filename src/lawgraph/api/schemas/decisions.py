"""Decision (vote) responses."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    DossierNameDTO,
    PathSource,
    StrictModel,
    WithPath,
    dossier_names_of,
)
from lawgraph.core.coalition import CoalitionPattern
from lawgraph.core.documents import chamber_of, number_in_dossier, numbered_in
from lawgraph.core.models import key_of
from lawgraph.core.votes import VoteChoice

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


_MOTION = (
    "The motion or amendment the decision was taken on: the oldest paper of the case the "
    "vote singled out (``primary_case_kind`` ``Motie`` or ``Amendement``), as its dictum "
    "and ``/api/decisions/{key}/document``; else the Kamerstuk it is about (a vote of the "
    "Eerste Kamer on a motion). Null for anything else, and for a case without a paper."
)


class DecisionMotionDTO(StrictModel):
    """The paper a decision was taken on: its node and readable address."""

    collection: str
    key: str
    path: str | None = None


class DecisionPaperDTO(WithPath):
    """The Kamerstuk a decision was taken on: the motion, the amendment or the bill."""

    path_source = PathSource("documents")

    id: str
    key: str
    kind: str | None = Field(None, description="As the chamber writes it: ``Motie``.")
    title: str | None = None
    number: str | None = Field(
        None,
        description="Its number in its dossier: the nr. of a Tweede Kamer paper (``31``), "
        "the letter of an Eerste Kamer one (``C``).",
    )
    dossier_number: str | None = Field(
        None, description="The dossier it is numbered in (``36764``, ``37020-XV``)."
    )
    date: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any], chamber: str | None) -> DecisionPaperDTO:
        """From a row of ``decision_document`` and the chamber of the decision."""
        light = row.get("light") or {}
        props = {**light, "number": row.get("number")}
        return cls(
            id=row["id"],
            key=key_of(row["id"]),
            kind=light.get("kind"),
            title=light.get("title") or light.get("display_name"),
            number=number_in_dossier(chamber, props),
            dossier_number=numbered_in(
                light.get("dossier_number"), light.get("dossier_suffix")
            ),
            date=light.get("date"),
            path_props=props,
        )


class VoteDTO(WithPath):
    """One vote cast on a decision, by a faction or — on a roll-call — a member."""

    path_source = PathSource(id_field="voter_id")

    voter_id: str = Field(
        ..., description="Node id (``collection/key``) of the member or faction."
    )
    voter_key: str
    name: str | None = None
    choice: str = Field(
        ..., description="The vote as the source wrote it: Voor, Tegen, Onthouden, …"
    )
    seats: int = 0

    @classmethod
    def from_row(cls, vote: dict[str, Any]) -> VoteDTO:
        """From a vote as ``get_decision_detail`` gives it: of a member with its slug, which
        makes its address."""
        fields = {k: v for k, v in vote.items() if k != "slug"}
        return cls(**fields, path_props={"slug": vote.get("slug")})


_DICTUM = (
    "Of a vote on a motion, what the motion asks or says, as it writes it: the lines from "
    "``verzoekt``, ``roept … op``, ``spreekt uit``, ``draagt … op`` or ``vraagt`` to "
    "``en gaat over tot de orde van de dag``; null for any other vote and for a motion "
    "without text."
)


class CoalitionVoteDTO(StrictModel):
    """What the coalition of the cabinet in office did on a vote of the Tweede Kamer
    (``semantic tk-coalition-votes``): the seats ``Voor`` and ``Tegen`` of the coalition and
    of the opposition (a faction with its seats that day, a member of a roll call as one)."""

    cabinet: str = Field(..., description="The key of the cabinet in office that day.")
    coalition_for: int
    coalition_against: int
    opposition_for: int
    opposition_against: int
    pattern: CoalitionPattern = Field(
        ...,
        description="`together`: every coalition seat on one side; `split`: on both; "
        "`wissel`: split, and the side with the most coalition seats lost (a "
        "wisselmeerderheid).",
    )
    carried: bool = Field(
        ..., description="Passed with the coalition's seats alone more than half cast."
    )
    decisive: bool = Field(
        ...,
        description="The opposition alone would have decided otherwise: the coalition's "
        "votes made the outcome.",
    )


class CoalitionFactionDTO(StrictModel):
    """A faction of the coalition on a vote: how its seats went."""

    key: str
    short: str | None = Field(None, description="Its abbreviation, else its name.")
    choice: VoteChoice | None = Field(
        None,
        description="``Voor`` or ``Tegen``; null when its seats went both ways (a "
        "roll call).",
    )
    seats_for: int
    seats_against: int


class DecisionDTO(WithPath):
    """One decision with every vote cast on it.

    ``vote_kind`` says who the votes come from: ``member`` for a roll-call
    (``hoofdelijke stemming``), ``faction`` otherwise. ``tally`` is seats per
    choice — members per choice on a roll-call — and ``voters`` is how many
    cast each choice.
    """

    path_source = PathSource("decisions")

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
    coalition: CoalitionVoteDTO | None = Field(
        None,
        description="What the coalition did on the vote; null without a cabinet, without "
        "a coalition vote, and in the Eerste Kamer.",
    )
    dictum: str | None = Field(None, description=_DICTUM)
    motion: DecisionMotionDTO | None = Field(None, description=_MOTION)
    primary_document: DecisionPaperDTO | None = Field(
        None,
        description="The Kamerstuk the vote was taken on, as ``/api/decisions/{key}/"
        "document`` finds it: the oldest paper of the case it singled out (a motion, an "
        "amendment, a bill), else of its other cases, else the Kamerstuk it is about (a "
        "vote of the Eerste Kamer); with its kind, title, number and dossier. Null without "
        "one.",
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        names: dict[str, dict[str, Any]],
        *,
        motion: dict[str, Any] | None = None,
        dictum: str | None = None,
        document: dict[str, Any] | None = None,
    ) -> DecisionDTO:
        """From the stored decision with its votes (``get_decision_detail``) and the names
        of the dossiers (``load_dossier_names``); with the motion it decided on and its
        dictum (``motion_documents``) and the paper it was taken on (``decision_document``)
        where the answer gives them, the detail of one decision."""
        props = doc.get("props") or {}
        chamber = props.get("chamber") or chamber_of(doc.get("labels"))
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
            chamber=chamber,
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
            votes=[VoteDTO.from_row(v) for v in doc.get("votes") or []],
            coalition=doc.get("coalition"),
            dictum=dictum,
            motion=DecisionMotionDTO(**motion) if motion else None,
            primary_document=(
                DecisionPaperDTO.from_row(document, chamber) if document else None
            ),
        )


class DecisionSummaryDTO(WithPath):
    """One row in the decision browser.

    ``tally`` sums the seats behind each choice — the number to show for a
    result — and ``voters`` counts how many factions (or members) made it.
    ``subject`` is that of the case the vote decided; a vote without a case of its own
    on an agenda item of several shares the item's subject with its siblings, and
    ``display_name`` (``Motie 2024Z17945: …``) and ``external_id`` tell them apart.
    """

    path_source = PathSource("decisions")

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
    dictum: str | None = Field(None, description=_DICTUM)
    motion: DecisionMotionDTO | None = Field(None, description=_MOTION)
    coalition: CoalitionVoteDTO | None = Field(
        None, description="What the coalition did on the vote, as on the detail."
    )


class DecisionKindCount(StrictModel):
    """How many of the decisions are of one kind, and how many of those carried and did
    not (the rest have no outcome)."""

    value: str | None
    count: int
    passed: int = 0
    rejected: int = 0


class DecisionOutcomeCount(StrictModel):
    """How many of the decisions carried (``true``), did not, or have no outcome (null)."""

    value: bool | None
    count: int


class DecisionDayCount(StrictModel):
    """The decisions of one day: how many, and how many of them carried."""

    date: str | None
    count: int
    passed: int


class DecisionYearCount(StrictModel):
    """The decisions of one year: how many, how many carried, how many did not."""

    year: str | None
    count: int
    passed: int
    rejected: int


class PartyVoteCount(StrictModel):
    """How a faction voted on some of the decisions: ``voor``, ``tegen``, and ``none``
    (another choice, or no vote of the faction: a roll-call vote is one of members)."""

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


class DecisionCoalitionCount(StrictModel):
    """How many of the decisions saw the coalition do this (``coalition`` filter values)."""

    value: str
    count: int


class DecisionCabinetCoalition(StrictModel):
    """What the coalition of one cabinet did on the decisions under every filter."""

    cabinet: str = Field(..., description="The key of the cabinet.")
    name: str | None = None
    votes: int = Field(..., description="The votes with a coalition vote of it.")
    together: int
    split: int
    wissel: int
    carried: int
    decisive: int


class DecisionFacets(StrictModel):
    """The decisions under the filters, counted.

    ``kind`` is counted without the ``kind`` filter and ``passed`` without the ``passed``
    filter, so each shows what choosing another value would give; ``days`` is counted
    under every filter.
    """

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
    coalition: list[DecisionCoalitionCount] = Field(
        default_factory=list,
        description="Under every filter but `coalition`: how many votes the coalition voted "
        "`together`, `split` (no wisselmeerderheid) or as a `wissel`, and how many it "
        "`carried` or was `decisive` on; those with none left out.",
    )
    coalition_cabinets: list[DecisionCabinetCoalition] = Field(
        default_factory=list,
        description="Under every filter (a topic of the Overzicht: its words, Kamer and "
        "period): per cabinet, newest first, what its coalition did on those votes.",
    )


class DecisionListResponse(StrictModel):
    """A page of decisions."""

    total: int | None = Field(
        ...,
        description="Matching decisions, independent of ``limit``; null while they are "
        "still being counted (``partial``) or not asked for (``facets=false``).",
    )
    items: list[DecisionSummaryDTO]
    # null when asked for without them (``facets=false``)
    facets: DecisionFacets | None = Field(default_factory=DecisionFacets)
    partial: bool = Field(
        False,
        description="Something is still being counted; ask again for it. ``total`` and "
        "``facets``: a filter not counted since the decisions last changed (a request waits "
        "3 s for them, then gets the page with ``total`` null and empty facets); "
        "``party_votes``, when asked for (every vote on every decision): ``[]`` now. The "
        "page itself is always whole.",
    )
