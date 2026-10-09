"""Dossier responses: lists, details, documents, timeline and mutations."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import FacetCountDTO, WithPath
from lawgraph.api.schemas.documents import (
    DocumentOrigin,
    SenderDTO,
    SigningCapacity,
    origin_fields,
    sender_of,
)
from lawgraph.config.settings import EK_ATTRIBUTION
from lawgraph.core.documents import document_sender, numbered_in, paper_number
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.tk_links import tk_url

# A dossier number as the API takes it: 29684, or its label with the addition of a
# budget chapter or a sub-series: 29684-I, 21501-31, 36956-(R2220).
DOSSIER_NUMBER_PATTERN = r"^\d+(-[A-Za-z0-9()]+)?$"

TitleSource = Literal["dossier", "document", "activiteit"]

DossierOutcome = Literal["aangenomen", "verworpen"]

KindBasis = Literal["case"]


class DossierPhaseDTO(BaseModel):
    """A phase of the bar of a bill."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ..., description="The phase, as the curated list ``phases`` names it."
    )
    chamber: Literal["TK", "EK"] = Field(
        "TK",
        description="The chamber of the phase: the bar is that of the Tweede Kamer.",
    )
    done: bool = Field(
        ...,
        description="A paper, an activity that took place or a decision on the bill "
        "marks it.",
    )
    date: str | None = Field(
        None, description="The first date of those; null for none."
    )


class EkOutcomeDTO(BaseModel):
    """The outcome of the bill of a dossier in the Eerste Kamer, as eerstekamer.nl gives it."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["Aangenomen", "Verworpen"] = Field(
        ..., description="As the Eerste Kamer shows it."
    )
    date: str | None = Field(None, description="The day of the vote.")
    method: str | None = Field(
        None,
        description="How it was decided, as the report names it: ``Hamerstuk``, "
        "``Stemming bij zitten en opstaan, aangenomen``, ``Hoofdelijke stemming, "
        "verworpen``; null for a rejection known from the list of rejected bills alone "
        "(before June 2015).",
    )
    source_url: str | None = Field(
        None,
        description="The page it was taken over from: the report of the vote, or the list "
        "of rejected bills.",
    )
    retrieved_on: str | None = Field(None, description="The day it was taken over.")
    attribution: str = Field(
        ...,
        description="The source to name with it (``EK_ATTRIBUTION``), with ``source_url`` "
        "and ``retrieved_on``: the terms of eerstekamer.nl allow reuse with the source "
        "and the day it was taken over.",
    )


class TkDecisionDTO(BaseModel):
    """The last decision of the Tweede Kamer on the bill of a dossier."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        ...,
        description="``BesluitSoort`` as the Kamer writes it: ``Stemmen - aangenomen``, "
        "``Stemmen - zonder stemming aannemen`` (a hamerstuk), ``Stemmen - verworpen``, "
        "``Stemmen - uitstellen``, ...",
    )
    text: str | None = Field(None, description="``BesluitTekst``: ``Aangenomen.``")
    date: str | None = None


class TimelineCommitteeDTO(WithPath):
    """The committee that leads an activity, with its address (``/commissies/<slug>``)."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "committees"

    key: str
    slug: str | None = None
    name: str | None = None


class TimelineSignatoryDTO(WithPath):
    """Who signed the document a decision was taken on."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "members"
    path_key_field = "member_key"

    member_key: str | None = None
    name: str | None = None
    party: str | None = None
    role: str = Field(..., description="'indiener' or 'mede-indiener'.")
    source_role: str = Field("", description="The role as the source wrote it.")
    function: str | None = Field(
        None,
        description="The function they signed in, as the source writes it: 'Tweede "
        "Kamerlid', 'minister-president', 'vicepresident van de Raad van State'.",
    )
    capacity: SigningCapacity | None = Field(
        None,
        description="'bewindspersoon' (a minister or staatssecretaris), 'kamerlid' (signed "
        "for a faction) or 'overig' (the griffier, the Raad van State, ...).",
    )


class DocumentEntryDTO(DocumentOrigin, WithPath):
    """A document as it is named from another node: identity and paper number, never text."""

    path_dossier_is_label = True

    id: str
    key: str
    kind: str | None = None
    title: str | None = None
    sequence: int | None = Field(
        None, description="The number of the paper in ``dossier_number``."
    )
    number: str | None = Field(
        None,
        description="Its number in the dossier as its chamber numbers it: the nr. of a "
        "Tweede Kamer paper (``12``), the letter of an Eerste Kamer one (``A``).",
    )
    dossier_number: str | None = Field(
        None,
        description="The dossier the paper is numbered in (``31058``, ``37020-XV``): a "
        "paper is part of every dossier of its cases and a Kamerstuk of one. Null for a "
        "paper that is no Kamerstuk, such as a nader rapport sent along with a bill.",
    )
    session_year: str | None = Field(None, description="Parliamentary year.")
    date: str | None = None
    tk_url: str | None = None
    sender: SenderDTO | None = Field(
        None,
        description="Who sent a Tweede Kamer paper (``SenderDTO``); null for an Eerste "
        "Kamer paper and a paper without a signature.",
    )


class TimelineDocumentSummaryDTO(DocumentEntryDTO):
    """The document a decision was taken on: what it says and who signed it."""

    dictum_excerpt: str | None = Field(
        None, description="The first 280 characters of the document's text."
    )
    signatories: list[TimelineSignatoryDTO] = Field(default_factory=list)


class TimelineDocumentBody(DocumentOrigin):
    """A document entry: what identifies the document, never its text.

    Fetch ``/api/documents/{key}`` for the text. ``url`` is the page of an Eerste
    Kamer paper on officielebekendmakingen.nl; ``tk_url`` the paper on tweedekamer.nl.
    """

    kind: str | None = None
    title: str | None = None
    sequence: int | None = Field(
        None, description="The number of the paper in ``dossier_number``."
    )
    number: str | None = Field(
        None,
        description="Its number in the dossier: of the Tweede Kamer the nr. (``5``), of "
        "the Eerste Kamer the letter (``C``); null for none.",
    )
    dossier_number: str | None = Field(
        None,
        description="The dossier the paper is numbered in (``31058``, ``37020-XV``): a "
        "paper is part of every dossier of its cases and a Kamerstuk of one. Null for a "
        "paper that is no Kamerstuk, such as a nader rapport sent along with a bill.",
    )
    session_year: str | None = Field(None, description="Parliamentary year.")
    tk_url: str | None = None
    url: str | None = None
    sender: SenderDTO | None = Field(
        None,
        description="Who sent a Tweede Kamer paper (``SenderDTO``); null for an Eerste "
        "Kamer paper and a paper without a signature.",
    )


class TimelineActivityBody(BaseModel):
    """An activity entry: a debate, hearing or other agenda item."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(None, description="E.g. 'Commissiedebat'.")
    agenda_title: str | None = Field(
        None, description="The subject of the activity (``Activiteit.Onderwerp``)."
    )
    number: str | None = Field(None, description="The activity number.")
    status: str | None = Field(
        None,
        description="``Activiteit.Status`` as the source writes it: ``Gepland`` (still to "
        "come, also when its date has passed), ``Uitgevoerd``, ``Geannuleerd``, "
        "``Verplaatst``, ``Vervallen``; null when the source gives none (the Eerste "
        "Kamer gives none).",
    )
    chamber: Literal["TK", "EK"] = Field(
        "TK",
        description="``EK``: a block of a plenary sitting or a committee meeting of the "
        "Eerste Kamer, from its agenda on eerstekamer.nl.",
    )
    time: str | None = Field(
        None,
        description="Of the Eerste Kamer: the time its agenda gives (``13.30-13.35``, "
        "``14.15 uur``).",
    )
    source_url: str | None = Field(
        None,
        description="Of the Eerste Kamer: the page it was taken over from (reuse with the "
        "source named: ``EK_ATTRIBUTION``).",
    )
    retrieved_on: str | None = Field(
        None, description="Of the Eerste Kamer: the day that page was read."
    )


class TimelineDecisionBody(BaseModel):
    """A decision entry: the vote, and the document it was taken on.

    ``tally`` is seats per choice and ``voters`` how many factions (or members)
    cast each. ``document`` is the motion or amendment decided on, when it can be
    resolved.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    chamber: Literal["TK", "EK"] = Field(
        "TK",
        description="The chamber that decided: ``EK`` for a vote of the Eerste Kamer.",
    )
    result: str | None = Field(
        None,
        description="Of the Eerste Kamer: ``Aangenomen``, ``Verworpen`` as it shows it.",
    )
    method: str | None = Field(
        None,
        description="Of the Eerste Kamer: how it was decided, as its report names it "
        "(``Hamerstuk``, ``Stemming bij zitten en opstaan, aangenomen``).",
    )
    passed: bool | None = None
    vote_kind: str | None = None
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)
    external_id: str | None = Field(None, description="TK Besluit identifier.")
    primary_case_kind: str | None = Field(
        None,
        description="The ``Zaak.Soort`` of the case it decided: ``Wetgeving`` on the vote on "
        "a bill itself, ``Amendement`` or ``Motie`` on the others.",
    )
    document: TimelineDocumentSummaryDTO | None = None


class TimelineCommitmentBody(BaseModel):
    """A commitment (toezegging) entry."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    minister_name: str | None = None
    minister_role: str | None = None
    status: str | None = Field(
        None, description="The Toezegging.Status of the Tweede Kamer: `Openstaand`, …"
    )
    expected_resolution: str | None = None


class _TimelineEntry(BaseModel):
    """What every timeline entry has; the body and ``node_type`` say the rest."""

    model_config = ConfigDict(extra="forbid")

    date: str | None
    kind: str
    title: str | None
    node_id: str
    tk_url: str | None = None
    after_closure: bool = Field(
        False,
        description="Dated after the dossier's ``closed_on``: a follow-up letter, a debate "
        "or procedure meeting after the law was published. False for an open dossier.",
    )
    planned: bool = Field(
        False,
        description="An activity with ``status`` ``Gepland``: announced, not (yet) held.",
    )


class TimelineDocumentEntry(_TimelineEntry):
    """A document that is PART_OF the dossier."""

    node_type: Literal["document"]
    body: TimelineDocumentBody


class TimelineActivityEntry(_TimelineEntry):
    """An activity ABOUT the dossier; ``committee`` is null for a plenary one."""

    node_type: Literal["activity"]
    body: TimelineActivityBody
    committee: TimelineCommitteeDTO | None = None


class TimelineDecisionEntry(_TimelineEntry):
    """A decision ABOUT the dossier."""

    node_type: Literal["decision"]
    body: TimelineDecisionBody


class TimelineCommitmentEntry(_TimelineEntry):
    """A commitment ABOUT the dossier."""

    node_type: Literal["commitment"]
    body: TimelineCommitmentBody


TimelineEntryDTO = Annotated[
    TimelineDocumentEntry
    | TimelineActivityEntry
    | TimelineDecisionEntry
    | TimelineCommitmentEntry,
    Field(discriminator="node_type"),
]
_TIMELINE_ENTRY: TypeAdapter[TimelineEntryDTO] = TypeAdapter(TimelineEntryDTO)


def timeline_entry(row: dict[str, Any]) -> TimelineEntryDTO:
    """The typed entry for one timeline row of ``get_dossier_timeline``."""
    body = row.get("body") or {}
    node_type = row.get("node_type")
    link = tk_url(node_type, body)
    common = {
        "date": row.get("date"),
        "kind": row.get("kind") or "",
        "title": row.get("title"),
        "node_id": row.get("node_id") or "",
        "tk_url": link,
        "node_type": node_type,
        "after_closure": bool(row.get("after_closure")),
        "planned": bool(row.get("planned")),
    }
    if node_type == "document":
        origin = origin_fields(row.get("labels"), body.get("source"), body.get("kind"))
        common["body"] = {
            **{f: body.get(f) for f in ("kind", "title", "sequence", "session_year")},
            "number": paper_number(origin["chamber"], body),
            "dossier_number": numbered_in(
                body.get("dossier_number"), body.get("dossier_suffix")
            ),
            "tk_url": link,
            "url": body.get("url"),
            "sender": document_sender(body.get("actors"), row.get("date")),
            **origin,
        }
    elif node_type == "decision":
        common["body"] = {
            "subject": body.get("subject"),
            "chamber": body.get("chamber") or "TK",
            "result": body.get("result"),
            "method": body.get("method"),
            "passed": body.get("passed"),
            "vote_kind": body.get("vote_kind"),
            "tally": body.get("tally") or {},
            "voters": body.get("voters") or {},
            "external_id": body.get("decision_id"),
            "primary_case_kind": body.get("primary_case_kind"),
            "document": body.get("document"),
        }
    else:
        common["body"] = body
    if node_type == "activity":
        common["committee"] = row.get("committee")
    return _TIMELINE_ENTRY.validate_python(common)


class DossierDocumentDTO(DocumentEntryDTO):
    """One document linked to a dossier."""

    display_name: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DossierDocumentDTO:
        """From a document row of ``get_dossier_documents``."""
        origin = origin_fields(row.get("labels"), row.get("source"), row.get("kind"))
        return cls(
            id=row["id"],
            key=row["key"],
            kind=row.get("kind"),
            title=row.get("title"),
            sequence=row.get("sequence"),
            number=paper_number(origin["chamber"], row),
            dossier_number=numbered_in(
                row.get("dossier_number"), row.get("dossier_suffix")
            ),
            session_year=row.get("session_year"),
            date=row.get("date"),
            tk_url=tk_url("document", row),
            display_name=row.get("display_name"),
            sender=sender_of(row),
            **origin,
        )


class DossierDocumentsResponse(BaseModel):
    """Response for GET /api/dossiers/{number}/documents."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Documents in the dossier, independent of ``limit``."
    )
    items: list[DossierDocumentDTO]


class DossierSummaryDTO(WithPath):
    """A dossier in a list.

    ``kind`` is what the dossier is, as the Tweede Kamer names it: the ``Zaak.Soort`` of
    the zaak that is the dossier itself (``Wetgeving``, ``Initiatiefwetgeving``,
    ``Begroting``, ``Verdrag``, ``Initiatiefnota``, ``PKB/Structuurvisie``); null without
    one ("zonder soort": no kind is made up from its papers). ``kind_basis`` is ``case``
    with a kind. A bill (``Wetgeving``, ``Initiatiefwetgeving``, ``Begroting``) has
    ``phases``: every phase of the curated list in its order, each done when a paper, an
    activity or a decision of the Kamer marks it; ``current_phase`` is the furthest done
    phase in that order. A closed dossier has an ``outcome``: ``aangenomen`` (its law was
    published, or the Eerste Kamer adopted it) or ``verworpen`` (a chamber voted the bill
    down); ``tk_decision`` is the last decision of the Tweede Kamer on the bill and
    ``ek_outcome`` its outcome in the Eerste Kamer.
    """

    model_config = ConfigDict(extra="forbid")
    path_collection = "dossiers"

    id: str
    key: str
    number: str = Field(
        ...,
        description="Kamerstuknummer, e.g. 36558, or 37020-XV for a budget chapter.",
    )
    suffix: str | None = Field(
        None,
        description="The addition to the number (``Toevoeging``): ``XV`` of 37020-XV, "
        "``31`` of 21501-31; null for a dossier without one.",
    )
    same_number_count: int = Field(
        0,
        description="How many other dossiers share the number: 24 for each dossier of a "
        "budget of 25. ``GET /api/dossiers?number=`` lists them.",
    )
    title: str | None = None
    short_title: str | None = Field(
        None,
        description="The name a bill goes by, from the parentheses that end its title: "
        "``Verzamelwet gegevensbescherming``; null when the title has none.",
    )
    title_source: TitleSource | None = None
    kind: str | None = Field(
        None,
        description="``Zaak.Soort`` as the Kamer writes it: ``Wetgeving``, "
        "``Initiatiefwetgeving``, ``Begroting``, ``Verdrag``, ``Initiatiefnota``, "
        "``PKB/Structuurvisie``; null for none.",
    )
    kind_basis: KindBasis | None = Field(
        None,
        description="``case``: a zaak of the dossier gives the kind; null without a kind.",
    )
    phases: list[DossierPhaseDTO] | None = Field(
        None,
        description="Of a ``Wetgeving``, ``Initiatiefwetgeving`` or ``Begroting``: every "
        "phase of the bar in order; null for another kind.",
    )
    current_phase: str | None = Field(
        None,
        description="The furthest done phase in the order of ``phases`` (not the one with "
        "the latest date: the Kamer may date a paper by the day it was received); null for "
        "none.",
    )
    closed: bool = False
    outcome: DossierOutcome | None = None
    tk_decision: TkDecisionDTO | None = None
    ek_outcome: EkOutcomeDTO | None = None
    opened_on: str | None = Field(
        None,
        description="The day it opened, as the Kamer dates its papers: of nr. 1 of its own "
        "numbering, else of its Koninklijke boodschap, else of its first paper or activity "
        "(``opened_on_basis``).",
    )
    opened_on_basis: (
        Literal["first_paper", "royal_message", "earliest_record"] | None
    ) = None
    submitted_on_tk: str | None = Field(
        None,
        description="The day the bill was submitted to the Tweede Kamer, as it dates it: "
        "the ``Zaak.GestartOp`` of the dossier's own zaak of a bill (``Wetgeving``, "
        "``Initiatiefwetgeving``, ``Begroting``); null for another dossier.",
    )
    last_activity: str | None = Field(
        None,
        description="The day of its newest paper, activity that took place (not one only "
        "planned, cancelled or moved) or decision, as the Kamer dates them; null for none. "
        "``sort=last_activity`` lists the dossiers by it, newest first.",
    )
    closed_on: str | None = None
    ministry: MinistryKey | None = Field(
        None,
        description="The ministry (``GET /api/ministries``) of the bewindspersoon who "
        "signed the earliest signed document of the dossier first; null for an initiative "
        "or when nobody in government or parliament signed first.",
    )
    initiative: bool | None = Field(
        None,
        description="True when a Kamerlid signed the earliest signed document first, false "
        "when a bewindspersoon did, null when neither did.",
    )
    cabinet: str | None = Field(
        None,
        description="The key of the cabinet in office when that document was signed.",
    )

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierSummaryDTO:
        return cls(**_dossier_fields(doc))


class DossierListResponse(BaseModel):
    """A page of dossiers."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Matching dossiers, independent of limit and offset."
    )
    items: list[DossierSummaryDTO]
    facets: DossierFacetsDTO


class DossierFacetsDTO(BaseModel):
    """Per dimension the number of dossiers per value under the current filters, each
    dimension counted without its own filter (so the other values of a chosen dimension
    keep their counts), the largest first."""

    model_config = ConfigDict(extra="forbid")

    status: list[FacetCountDTO] = Field(default_factory=list)
    outcome: list[FacetCountDTO] = Field(default_factory=list)
    kind: list[FacetCountDTO] = Field(default_factory=list)
    phase: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)


DossierInstrumentRelation = Literal["legislated_in", "amends", "introduces", "repeals"]
DossierInstrumentStatus = Literal["canoniek", "voorgesteld"]


class DossierInstrumentLinkDTO(BaseModel):
    """One way a dossier is tied to an instrument."""

    model_config = ConfigDict(extra="forbid")

    relation: DossierInstrumentRelation
    status: DossierInstrumentStatus


class DossierInstrumentDTO(BaseModel):
    """An instrument a dossier is tied to, once, and every way it is.

    ``links`` holds each ``relation`` (``legislated_in``: the instrument came out of this
    dossier; ``amends``, ``introduces``, ``repeals``: the dossier changes it, resolved from
    the article or instrument that is changed to the parent instrument) with its
    ``status`` (``canoniek`` for what an amending publication enacted, ``voorgesteld`` for
    what a bill of the dossier proposes). ``relation`` and ``status`` are the first link:
    the enacted one before the proposed.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    celex: str | None = Field(None, description="Set on EU instruments.")
    display_name: str | None = None
    jurisdiction: str | None = Field(None, description="``nl`` or ``eu``.")
    relation: DossierInstrumentRelation
    status: DossierInstrumentStatus
    links: list[DossierInstrumentLinkDTO] = Field(default_factory=list)


def merge_instruments(rows: list[dict[str, Any]]) -> list[DossierInstrumentDTO]:
    """The hub rows (one per instrument, relation and status) as one item per instrument,
    in the order of their first row; an enacted link before a proposed one."""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = merged.setdefault(row["id"], {**row, "links": []})
        link = {"relation": row["relation"], "status": row["status"]}
        if link not in item["links"]:
            item["links"].append(link)
    items = []
    for item in merged.values():
        item["links"].sort(key=lambda link: link["status"] != "canoniek")
        item["relation"], item["status"] = (
            item["links"][0]["relation"],
            item["links"][0]["status"],
        )
        items.append(DossierInstrumentDTO(**item))
    return items


# What a link of the dossier hub says of a change: proposed by a bill, or enacted.
_CHANGE_BASIS = {"voorgesteld": "voorstel", "canoniek": "staatsblad"}
_CHANGES = ("amends", "introduces", "repeals")


class LegalEffectItemDTO(BaseModel):
    """An instrument the dossier changes or implements."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str | None = Field(
        None,
        description="The citation title, else the title: `Wet op het financieel toezicht`.",
    )
    short: str | None = Field(
        None,
        description="The short title the source gives (the WTI afkorting: `Wft`); null "
        "where it gives none.",
    )
    bwb_id: str | None = None
    celex: str | None = None
    basis: list[str] = Field(
        default_factory=list,
        description="Where it shows: `voorstel` (a bill of the dossier proposes the change), "
        "`staatsblad` (an amending publication of the dossier enacted it), `wet` (the act of "
        "the dossier implements it).",
    )


class LegalEffectDTO(BaseModel):
    """What the dossier's law changes and implements, in the order its title names them."""

    model_config = ConfigDict(extra="forbid")

    amends: list[LegalEffectItemDTO] = Field(
        default_factory=list,
        description="The laws it amends, adds to or repeals from (never its own new act).",
    )
    implements: list[LegalEffectItemDTO] = Field(
        default_factory=list, description="The EU acts it implements."
    )


def legal_effect(
    hub_rows: list[dict[str, Any]],
    implements: list[dict[str, Any]],
    names: dict[str, dict[str, Any]],
    title: str | None,
) -> LegalEffectDTO:
    """The legal effect of a dossier from its hub rows (``get_dossier_hub``: a change a bill
    proposes or a publication enacted, to the parent instrument), the acts it implements
    (``get_dossier_implements``) and the names of those instruments; each in the order the
    title names it, then by name."""
    own = {row["id"] for row in hub_rows if row.get("relation") == "legislated_in"}
    amends: dict[str, list[str]] = {}
    for row in hub_rows:
        basis = _CHANGE_BASIS.get(row.get("status") or "")
        if (
            row.get("relation") in _CHANGES
            and row["id"] not in own
            and not row.get("celex")
        ):
            _add(amends, row["id"], basis)
    implemented: dict[str, list[str]] = {}
    for row in implements:
        _add(implemented, row["id"], row.get("basis"))
    return LegalEffectDTO(
        amends=_items(amends, names, title),
        implements=_items(implemented, names, title),
    )


def _add(found: dict[str, list[str]], instrument_id: str, basis: str | None) -> None:
    bases = found.setdefault(instrument_id, [])
    if basis and basis not in bases:
        bases.append(basis)


def _items(
    found: dict[str, list[str]], names: dict[str, dict[str, Any]], title: str | None
) -> list[LegalEffectItemDTO]:
    lowered = (title or "").lower()

    def place(instrument_id: str) -> tuple[int, str]:
        named = names.get(instrument_id) or {}
        positions = [
            lowered.find(str(text).lower())
            for text in (named.get("name"), named.get("short"))
            if text and str(text).lower() in lowered
        ]
        return (
            min(positions) if positions else len(lowered) + 1,
            named.get("name") or "",
        )

    return [
        LegalEffectItemDTO(**names[instrument_id], basis=found[instrument_id])
        for instrument_id in sorted(found, key=place)
        if instrument_id in names
    ]


class DossierLawNamedDTO(BaseModel):
    """A law the title of a dossier names, and whether the graph holds it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ..., description="As the title writes it: `Wetboek van Strafvordering`."
    )
    loaded: bool = Field(..., description="Whether the graph holds the law.")
    key: str | None = Field(None, description="The instrument key when it does.")
    bwb_id: str | None = None


class DossierCommitteeDTO(TimelineCommitteeDTO):
    """A committee that leads an activity about a dossier."""

    id: str
    abbreviation: str | None = None
    role: Literal["lead"] = "lead"


class EkPaperDTO(BaseModel):
    """A paper of a step of a bill, as the page of the Eerste Kamer lists it."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        ..., description="As the page names it: ``verslag``, ``stemming (hamerstuk)``."
    )
    date: str | None = None
    number: str | None = Field(
        None, description="As the page writes it: ``EK, B``, ``TK, 2``; null for none."
    )
    url: str


class EkStepDTO(BaseModel):
    """A step of the progress of a bill, as the page of the Eerste Kamer shows it."""

    model_config = ConfigDict(extra="forbid")

    phase: str | None = Field(
        None,
        description="``Schriftelijke voorbereiding``, ``Plenair``, ``Afkondiging``; null "
        "for the first step, in the Tweede Kamer.",
    )
    house: str | None = Field(
        None,
        description="``Tweede Kamer``, ``Eerste Kamer``, ``Staatsblad(en)``; null where the "
        "page names none (the plenary step of the Eerste Kamer).",
    )
    state: str | None = Field(
        None,
        description="As the page marks it: ``vol`` (it drew the step full: done), "
        "``geblokt`` (the step the bill is in), ``leeg`` (not reached).",
    )
    papers: list[EkPaperDTO] = Field(default_factory=list)


class EkBillSourceDTO(BaseModel):
    """The page of the bill on eerstekamer.nl."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    read_on: str | None = None
    attribution: str = EK_ATTRIBUTION


class DossierSenateDTO(BaseModel):
    """The Eerste Kamer papers among a dossier's documents, and the page of its bill on
    eerstekamer.nl."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = 0
    first_date: str | None = Field(
        default=None, description="Date of the earliest paper (YYYY-MM-DD)."
    )
    submitted_on: str | None = Field(
        default=None,
        description="The day the page of the bill says it was submitted (``Kerngegevens``: "
        "``ingediend``); null without a page.",
    )
    status: str | None = Field(
        default=None,
        description="Where it is, as the list of its committee heads it: ``In schriftelijke "
        "voorbereiding``, ``Gereed voor plenaire behandeling door de Eerste Kamer``, "
        "``Plenaire behandeling Eerste Kamer afgerond``; null for a bill on no such list.",
    )
    progress: list[EkStepDTO] = Field(
        default_factory=list,
        description="The progress of the bill as its page shows it, step by step; empty "
        "without a page. What the page does not show is not here.",
    )
    source: EkBillSourceDTO | None = Field(
        default=None, description="The page it was taken over from; null without one."
    )


DossierRelationName = Literal[
    "revises", "accompanies", "related_to", "second_reading_of"
]


class DossierRelationDTO(BaseModel):
    """A relation between this dossier and another, and which way it points.

    * ``revises``: a supplementary budget or a slotwet revises the budget of its chapter
      and year; ``rule`` says which (``begrotingswijziging`` or ``slotwet``).
    * ``accompanies``: a budget change is submitted with the ``nota`` its title names
      (``voorjaarsnota``, ``najaarsnota``, ``miljoenennota``).
    * ``related_to``: the Kamer relates a case of the one dossier to a case of the other
      (``Zaak.GerelateerdNaar``), mostly a letter of the government to the motion it
      answers. ``cases`` counts the pairs of cases, ``case_kinds`` names their kinds
      (``Brief regering → Motie``).
    * ``second_reading_of``: a change in the Grondwet in its second reading and the dossier of
      its first reading, whose papers explain it: the memorandum of 35785 only refers to those
      of 35418 and 35419.

    ``outgoing`` means this dossier is the subject: 37035-XXII revises 36800-XXII and
    accompanies 37020. On 36800-XXII the same ``revises`` is ``incoming``.
    """

    model_config = ConfigDict(extra="forbid")

    relation: DossierRelationName
    direction: Literal["outgoing", "incoming"]
    dossier: DossierSummaryDTO
    cases: int | None = None
    case_kinds: list[str] = Field(default_factory=list)
    rule: Literal["begrotingswijziging", "slotwet"] | None = None
    nota: Literal["voorjaarsnota", "najaarsnota", "miljoenennota"] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DossierRelationDTO:
        meta = row.get("meta") or {}
        return cls(
            relation=cast(DossierRelationName, str(row["relation"]).lower()),
            direction=row["direction"],
            dossier=DossierSummaryDTO.from_document(row["dossier"]),
            cases=meta.get("cases"),
            case_kinds=list(meta.get("case_kinds") or []),
            rule=meta.get("rule"),
            nota=meta.get("nota"),
        )


class NextActivityDTO(BaseModel):
    """An activity the Tweede Kamer has planned."""

    model_config = ConfigDict(extra="forbid")

    key: str
    date: str | None = None
    kind: str | None = Field(
        default=None,
        description="``Activiteit.Soort``: ``Commissiedebat``, ``Plenair debat``, "
        "``Stemmingen``, …",
    )
    agenda_title: str | None = None
    committee: dict[str, Any] | None = Field(
        default=None,
        description="Its lead committee (``key``, ``slug``, ``name``); null in plenary.",
    )


class DossierDetailResponse(DossierSummaryDTO):
    """A dossier with the size of everything attached to it, and what it links to."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = 0
    activity_count: int = 0
    decision_count: int = 0
    commitment_count: int = 0
    instruments: list[DossierInstrumentDTO] = Field(
        default_factory=list,
        description=(
            "Instruments legislated in, amended, introduced or repealed by the "
            "dossier, one item per instrument with every link."
        ),
    )
    legal_effect: LegalEffectDTO = Field(
        default_factory=LegalEffectDTO,
        description="What the dossier's law changes and implements: from its bills (proposed) "
        "and its publications and act (enacted), the order its title names them.",
    )
    laws_named: list[DossierLawNamedDTO] = Field(
        default_factory=list,
        description=(
            "The laws the title names (`Wetboek van Strafrecht`, `Vreemdelingenwet 2000`), "
            "each with whether the graph holds it: a law the dossier changes that is not "
            "loaded has no instrument above."
        ),
    )
    committees: list[DossierCommitteeDTO] = Field(
        default_factory=list,
        description="Committees leading an activity about the dossier.",
    )
    documents_by_kind: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Documents per kind (``Motie``, ``Amendement``, ...); a document "
            "without a kind is not counted."
        ),
    )
    senate: DossierSenateDTO = Field(default_factory=lambda: DossierSenateDTO())
    next_activity: NextActivityDTO | None = Field(
        default=None,
        description="The next thing the Tweede Kamer has planned about the dossier: the "
        "earliest of its activities with status ``Gepland`` (``Activiteit.Status``) from "
        "today on; null when it plans nothing. The Kamer gives no next phase as data: a "
        "planned debate or vote is an activity like any other.",
    )
    relations: list[DossierRelationDTO] = Field(
        default_factory=list,
        description=(
            "The dossiers this one revises, accompanies or is related to, and those that "
            "revise, accompany or relate to it: by relation, then outgoing before incoming, "
            "then in the order of their numbers. All dossiers of its own number are "
            "``GET /api/dossiers?number=``."
        ),
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        counts: dict[str, int] | None = None,
        hub: dict[str, Any] | None = None,
        relations: list[dict[str, Any]] | None = None,
        laws_named: list[dict[str, Any]] | None = None,
        next_activity: dict[str, Any] | None = None,
        legal_effect: LegalEffectDTO | None = None,
    ) -> DossierDetailResponse:
        counts = counts or {}
        hub = hub or {}
        return cls(
            **_dossier_fields(doc),
            document_count=counts.get("documents", 0),
            activity_count=counts.get("activities", 0),
            decision_count=counts.get("decisions", 0),
            commitment_count=counts.get("commitments", 0),
            instruments=merge_instruments(hub.get("instruments") or []),
            laws_named=[DossierLawNamedDTO(**law) for law in laws_named or []],
            legal_effect=legal_effect or LegalEffectDTO(),
            committees=[DossierCommitteeDTO(**c) for c in hub.get("committees") or []],
            documents_by_kind=dict(hub.get("documents_by_kind") or {}),
            senate=_senate(
                hub.get("senate") or {}, (doc.get("props") or {}).get("ek_bill")
            ),
            relations=[DossierRelationDTO.from_row(r) for r in relations or []],
            next_activity=(
                NextActivityDTO.model_validate(next_activity) if next_activity else None
            ),
        )


def _senate(counted: dict[str, Any], bill: dict[str, Any] | None) -> DossierSenateDTO:
    """The Eerste Kamer of a dossier: its papers counted, and the page of its bill."""
    if not bill:
        return DossierSenateDTO.model_validate(counted)
    return DossierSenateDTO.model_validate(
        {
            **counted,
            "submitted_on": bill.get("submitted_on"),
            "status": bill.get("status"),
            "progress": bill.get("progress") or [],
            "source": {"url": bill.get("url"), "read_on": bill.get("read_on")},
        }
    )


def _dossier_fields(doc: dict[str, Any]) -> dict[str, Any]:
    props = doc.get("props") or {}
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "number": props.get("label") or "",
        "suffix": props.get("suffix") or None,
        "same_number_count": int(props.get("same_number_count") or 0),
        "title": props.get("title"),
        "short_title": short_title(props.get("title")),
        "title_source": props.get("title_source"),
        "kind": props.get("kind"),
        "kind_basis": props.get("kind_basis"),
        "phases": props.get("phases"),
        "current_phase": props.get("current_phase"),
        "closed": bool(props.get("closed")),
        "outcome": (
            props.get("outcome")
            if props.get("outcome") in get_args(DossierOutcome)
            else None
        ),
        "tk_decision": props.get("tk_decision"),
        "ek_outcome": (
            {**props["ek_outcome"], "attribution": EK_ATTRIBUTION}
            if props.get("ek_outcome")
            else None
        ),
        "opened_on": props.get("opened_on"),
        "opened_on_basis": props.get("opened_on_basis"),
        "submitted_on_tk": props.get("submitted_on_tk"),
        "last_activity": props.get("last_activity"),
        "closed_on": props.get("closed_on"),
        "ministry": props.get("ministry"),
        "initiative": props.get("initiative"),
        "cabinet": props.get("cabinet"),
    }


class DossierTimelineResponse(BaseModel):
    """Everything that happened in a dossier, in date order."""

    model_config = ConfigDict(extra="forbid")

    number: str
    total: int
    order: str
    entries: list[TimelineEntryDTO]


DossierMutationKind = Literal["mutation", "explanation"]


class DossierMutationNode(WithPath):
    """A node in the pending-change subgraph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    kind: DossierMutationKind

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierMutationNode:
        node_id = doc.get("_id", "")
        return cls(
            id=node_id,
            key=doc.get("_key", ""),
            collection=node_id.split("/")[0] if "/" in node_id else "",
            type=doc.get("type", ""),
            display_name=(doc.get("props") or {}).get("display_name"),
            labels=list(doc.get("labels") or []),
            kind=doc.get("_kind", "mutation"),
        )


class DossierMutationEdge(BaseModel):
    """An edge in the pending-change subgraph."""

    model_config = ConfigDict(extra="forbid")

    from_id: str | None
    to_id: str | None
    relation: str | None
    status: str | None
    meta: dict[str, Any] | None = None
    kind: DossierMutationKind


class DossierMutationsResponse(BaseModel):
    """The pending-change subgraph of a dossier, shaped like the graph endpoint."""

    model_config = ConfigDict(extra="forbid")

    number: str
    nodes: list[DossierMutationNode]
    edges: list[DossierMutationEdge]
