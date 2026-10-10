"""The news feed: dated events of the graph, newest first."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal, cast, get_args
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import FacetCountDTO, WithPath
from lawgraph.api.schemas.decisions import CoalitionVoteDTO
from lawgraph.api.schemas.stats import DataAsOfDTO
from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
)
from lawgraph.core.documents import paper_number
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.feed import (
    DOCUMENT_EVENTS,
    EVENT_BILL,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_JUDGMENT,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    ROLE_SUBMITTER,
    person_role,
)
from lawgraph.core.models import parse_node_id
from lawgraph.core.official_urls import instrument_url, judgment_url
from lawgraph.core.tk_links import document_page
from lawgraph.core.tk_records import CAPACITY_MEMBER, NO_DUE_DATE

# The values of ``core.feed.FEED_KINDS`` and ``PERSON_ROLES``.
FeedKind = Literal[
    "toezegging",
    "Voorstel van wet",
    "Nota van wijziging",
    "Amendement",
    "Motie",
    "stemming",
    "publicatie",
    "inwerkingtreding",
    "Brief regering",
    "uitspraak",
]
PersonRole = Literal["indiener", "medeindiener", "bewindspersoon"]
PublicationSeries = Literal["stb", "stcrt", "trb"]
ShortTitleBasis = Literal["title", "citation", "case", "amended_law"]

_OUTCOME = {True: "aangenomen", False: "verworpen"}


class FeedNodeDTO(BaseModel):
    """The node an event is: ``/api/nodes/{collection}/{key}`` shows it."""

    model_config = ConfigDict(extra="forbid")

    collection: str
    key: str


class FeedDossierDTO(WithPath):
    model_config = ConfigDict(extra="forbid")
    path_collection = "dossiers"

    key: str
    number: str = Field(..., description="The label: ``36600-VII``, a path segment.")
    title: str | None = None
    short_title: str | None = Field(
        None,
        description="The name it goes by: of a budget its chapter and year, else the "
        "parentheses that end its title, else the citation title its bill gives itself, "
        "the Kamer gives the bill's case, or of the one law the bill changes; null "
        "without.",
    )
    short_title_basis: ShortTitleBasis | None = Field(
        None,
        description="Where ``short_title`` comes from: ``title``, ``citation``, ``case`` "
        "or ``amended_law`` (then it names the law changed, not the bill).",
    )


class FeedFactionDTO(WithPath):
    model_config = ConfigDict(extra="forbid")
    path_collection = "factions"

    key: str
    short: str | None = Field(None, description="Its abbreviation: ``VVD``.")


class FeedPersonDTO(WithPath):
    """Someone who signed the event: submitted a paper (``indiener``), signed it with the
    one who did (``medeindiener``), or signed it or made the commitment for the
    government (``bewindspersoon``)."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "members"

    key: str | None = Field(None, description="Member key; null when unknown.")
    name: str | None = Field(
        None, description="The name they go by and the surname: ``Hanneke Steen``."
    )
    surname: str | None = Field(
        None, description="With its prefix, as written: ``van der Plas``."
    )
    function: str | None = Field(
        None,
        description="What they signed as, as the source writes it: ``minister van "
        "Sociale Zaken en Werkgelegenheid``, ``Tweede Kamerlid``.",
    )
    role: PersonRole
    faction: FeedFactionDTO | None = Field(
        None,
        description="The faction a Kamerlid signed for; null for a bewindspersoon.",
    )


class FeedCoalitionFactionDTO(BaseModel):
    """A faction of the coalition on a vote: how its seats went."""

    model_config = ConfigDict(extra="forbid")

    key: str
    short: str | None = Field(None, description="Its abbreviation, else its name.")
    choice: Literal["Voor", "Tegen"] | None = Field(
        None,
        description="``Voor`` or ``Tegen``; null when its seats went both ways (a "
        "roll call).",
    )
    seats_for: int
    seats_against: int


class FeedVoteDTO(BaseModel):
    """The outcome of a ``stemming``."""

    model_config = ConfigDict(extra="forbid")

    chamber: Literal["TK", "EK"] = Field(
        "TK",
        description="The chamber that voted; of the Eerste Kamer only the vote that decided "
        "the bill is an event.",
    )
    passed: bool | None = None
    outcome: Literal["aangenomen", "verworpen"] | None = None
    vote_kind: Literal["member", "faction"] | None = Field(
        None, description="``member`` for a roll-call, ``faction`` otherwise."
    )
    tally: dict[str, int] = Field(
        default_factory=dict,
        description="Seats per choice as the source writes it (``Voor``, ``Tegen``, "
        "``Niet deelgenomen``); members per choice on a roll-call.",
    )
    method: str | None = Field(
        None,
        description="Of the Eerste Kamer: how it was decided, as its report names it "
        "(``Hamerstuk``, ``Stemming bij zitten en opstaan, aangenomen``, ``Hoofdelijke "
        "stemming, verworpen``).",
    )
    decision_kind: str | None = Field(
        None,
        description="Of the Tweede Kamer: its ``BesluitSoort`` as the Kamer writes it "
        "(``Stemmen - aangenomen``, ``Stemmen - zonder stemming aannemen``: a hamerstuk, "
        "no votes).",
    )
    coalition: CoalitionVoteDTO | None = Field(
        None,
        description="Of the Tweede Kamer: what the coalition of the cabinet in office did, "
        "as ``GET /api/decisions/{key}`` gives it; null without a cabinet or a coalition "
        "vote, and of the Eerste Kamer.",
    )
    coalition_factions: list[FeedCoalitionFactionDTO] = Field(
        default_factory=list,
        description="Of the Tweede Kamer: each coalition faction that cast a seat, with its "
        "choice, most seats first; empty where ``coalition`` is null.",
    )


class FeedCommitmentDTO(BaseModel):
    """What a ``toezegging`` stands at."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(
        None, description="Of a commitment: its Toezegging.Status (`Openstaand`)."
    )
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )


class FeedInstrumentDTO(BaseModel):
    """A law the event is about."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str | None = None
    official_url: str | None = None


class FeedPublicationDTO(BaseModel):
    """A ``publicatie`` in the Staatsblad, the Staatscourant or the Tractatenblad."""

    model_config = ConfigDict(extra="forbid")

    series: PublicationSeries | None = None
    year: int | None = None
    number: str | None = None
    instruments: list[FeedInstrumentDTO] = Field(
        default_factory=list,
        description="The laws it amends, introduces or repeals (or articles of), by title; "
        "at most ten.",
    )


class FeedCommencementDTO(BaseModel):
    """An ``inwerkingtreding``: a new version of a law in force from ``date``."""

    model_config = ConfigDict(extra="forbid")

    instrument: FeedInstrumentDTO | None = None
    article_count: int | None = Field(None, description="The articles of the law.")
    changed_articles: int = Field(
        0, description="The articles with a version that begins that day."
    )


class FeedJudgmentDTO(WithPath):
    """An ``uitspraak``: a judgment or conclusion published on ``date`` (its ``Datum
    publicatie``), of the highest courts unless a ``tier`` is asked for."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "judgments"

    ecli: str | None = None
    court: str | None = Field(None, description="ECLI court code, `HR`, `RVS`.")
    tier: str | None = Field(None, description="As in `/api/judgments`.")
    court_kind: str | None = None
    decision_kind: str | None = Field(
        None, description="`arrest`, `uitspraak`, `conclusie`, ..."
    )
    procedure: str | None = Field(
        None, description="As the source gives it: `Cassatie`, `Hoger beroep`."
    )
    decided_on: str | None = Field(
        None,
        description="The date of the decision (YYYY-MM-DD), before its publication.",
    )
    advocate_general: str | None = Field(
        None, description="Of a conclusion, who wrote it (as on the detail)."
    )
    advocate_general_role: str | None = None


class FeedHeadlineDTO(BaseModel):
    """The parts a headline is made of; the front end makes the sentence."""

    model_config = ConfigDict(extra="forbid")

    surname: str | None = Field(
        None,
        description="Of the first submitter (``indiener``): ``van der Plas`` of "
        "``motie-Van der Plas``; null without one.",
    )
    subject: str | None = Field(
        None,
        description="What the title says it is about: the part after the first "
        "`` over ``; null when it has none.",
    )
    short_title: str | None = Field(
        None,
        description="The short title of the event's dossier (``dossier.short_title``).",
    )


class FeedItemDTO(WithPath):
    """One event."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="``collection/key`` of its node: unique.")
    kind: FeedKind
    date: str = Field(..., description="YYYY-MM-DD; the source gives no time of day.")
    title: str | None = None
    summary: str | None = Field(
        None,
        description="The whole text of a commitment, the decision of a vote "
        "(``Aangenomen.``), the inhoudsindicatie of a judgment; null for the other kinds.",
    )
    has_text: bool | None = Field(
        None,
        description="Of a paper: whether its text is in the data, so that it can be "
        "opened (a new paper's text follows its PDF by days); null for the other kinds.",
    )
    dictum: str | None = Field(
        None,
        description="Of a motion: what it asks or says (``verzoekt de regering …``), as "
        "``GET /api/documents/{key}`` gives it; null for the other kinds and a motion "
        "without text.",
    )
    subkind: str | None = Field(
        None,
        description="What the source calls it: the document kind (``Motie (gewijzigd/"
        "nader)``), for a vote what was voted on (the ``Zaak.Soort``: ``Motie``, "
        "``Amendement``, ``Wetgeving``, ...); null for the other kinds.",
    )
    node: FeedNodeDTO
    dossier: FeedDossierDTO | None = Field(
        None, description="Its first dossier; null for an event without one."
    )
    persons: list[FeedPersonDTO] = Field(
        default_factory=list,
        description="Who signed it, in the order of the source: the submitters of a "
        "paper, of the paper a vote decided, the bewindspersoon of a commitment.",
    )
    ministry: MinistryKey | None = Field(
        None,
        description="Of a commitment its own; otherwise the ministry that brought its "
        "dossier in (``ministry`` of the dossier).",
    )
    cabinet: str | None = Field(None, description="The cabinet in office on ``date``.")
    official_url: str | None = Field(
        None, description="The official text of a publication or a version of a law."
    )
    tk_url: str | None = Field(
        None, description="The page of a paper on tweedekamer.nl."
    )
    number: str | None = Field(
        None,
        description="Of a paper its nr. in its dossier (``12``); null for the other kinds.",
    )
    headline: FeedHeadlineDTO
    vote: FeedVoteDTO | None = None
    commitment: FeedCommitmentDTO | None = None
    publication: FeedPublicationDTO | None = None
    commencement: FeedCommencementDTO | None = None
    judgment: FeedJudgmentDTO | None = None

    @classmethod
    def from_row(
        cls, row: dict[str, Any], slugs: dict[str, str] | None = None
    ) -> FeedItemDTO:
        kind = row["kind"]
        props = row.get("props") or {}
        collection, key = parse_node_id(row["id"])
        dossier = row.get("dossier")
        title = _title(kind, props, row)
        persons = _persons(kind, row, slugs or {})
        short, basis = _dossier_short_title(dossier) if dossier else (None, None)
        return cls(
            id=row["id"],
            path_props=_path_props(collection, props),
            kind=kind,
            date=row["date"],
            title=title,
            summary=_summary(kind, props, row),
            has_text=row.get("has_text") if kind in DOCUMENT_EVENTS else None,
            dictum=row.get("dictum") if kind in DOCUMENT_EVENTS else None,
            subkind=_subkind(kind, props),
            node=FeedNodeDTO(collection=collection, key=key),
            dossier=(
                FeedDossierDTO(
                    key=dossier["key"],
                    number=dossier["number"],
                    title=dossier.get("title"),
                    short_title=short,
                    short_title_basis=basis,
                )
                if dossier
                else None
            ),
            persons=persons,
            headline=FeedHeadlineDTO(
                surname=next(
                    (p.surname for p in persons if p.role == ROLE_SUBMITTER), None
                ),
                subject=_subject(title),
                short_title=short,
            ),
            ministry=row.get("ministry"),
            cabinet=row.get("cabinet"),
            official_url=_official_url(kind, props),
            tk_url=document_page(props.get("document_number"))
            if kind in DOCUMENT_EVENTS
            else None,
            number=paper_number(CHAMBER_TK, props) if kind in DOCUMENT_EVENTS else None,
            vote=_vote(props, row) if kind == EVENT_VOTE else None,
            commitment=_commitment(props) if kind == EVENT_COMMITMENT else None,
            publication=_publication(props, row) if kind == EVENT_PUBLICATION else None,
            commencement=_commencement(row) if kind == EVENT_COMMENCEMENT else None,
            judgment=_judgment(props) if kind == EVENT_JUDGMENT else None,
        )


# The props a paper's or a commitment's readable address is made of (``path_of``): its own
# dossier number and suffix and its number in the dossier, or the number of a commitment.
# The fields of the item do not say them (``number`` is the nr. alone, ``dossier`` the
# first dossier by its label).
_PATH_PROPS = ("dossier_number", "dossier_suffix", "sequence", "number")


def _path_props(collection: str, props: dict[str, Any]) -> dict[str, Any] | None:
    if collection not in (COLLECTION_DOCUMENTS, COLLECTION_COMMITMENTS):
        return None
    return {field: props[field] for field in _PATH_PROPS if field in props}


def _title(kind: str, props: dict[str, Any], row: dict[str, Any]) -> str | None:
    title = _source_title(kind, props, row)
    return " ".join(title.split()) if title else None


def _source_title(kind: str, props: dict[str, Any], row: dict[str, Any]) -> str | None:
    """A bill by the title of its dossier (the paper is called ``Voorstel van wet``), a
    commitment by its first words, a publication by its citation title, a version by the
    title of its law, any other paper or a vote by its subject."""
    if kind == EVENT_BILL:
        named = [props.get("title"), props.get("subject")]
        own = [
            t
            for t in named
            if t and not t.strip().lower().startswith("voorstel van wet")
        ]
        return (
            (row.get("dossier") or {}).get("title") or next(iter(own), None) or named[0]
        )
    if kind == EVENT_COMMITMENT:
        return props.get("display_name") or row.get("text")
    if kind == EVENT_COMMENCEMENT:
        return (row.get("instrument") or {}).get("title") or props.get("bwb_id")
    if kind in (EVENT_PUBLICATION, EVENT_JUDGMENT):
        return props.get("citation_title") or props.get("display_name")
    return props.get("subject") or props.get("title")


def _summary(kind: str, props: dict[str, Any], row: dict[str, Any]) -> str | None:
    if kind == EVENT_COMMITMENT:
        return row.get("text")
    if kind == EVENT_VOTE:
        return props.get("decision_text")
    if kind == EVENT_JUDGMENT:
        return props.get("summary")
    return None


def _subkind(kind: str, props: dict[str, Any]) -> str | None:
    if kind in DOCUMENT_EVENTS or kind == EVENT_VOTE:
        return props.get("kind")
    return None


# "Motie van het lid Bakker over gemeenten": what comes after the first " over ".
_ABOUT = re.compile(r"\sover\s+(.+)$", re.DOTALL)
# An initial as a paper writes it before the surname: "D.J.", "Th.", "A.C.".
_INITIAL = re.compile(r"^(?:[A-Z][a-z]?\.)+$")


def _subject(title: str | None) -> str | None:
    match = _ABOUT.search(title or "")
    return (match.group(1).strip() or None) if match else None


def _surname(signature: dict[str, Any]) -> str | None:
    """The surname with its prefix: from the name on the paper without its initials
    (``D.J. van den Berg``), or before the comma (``Vijlbrief, J.A.``), else the member's
    name without the name they go by."""
    written = (signature.get("name") or "").strip()
    if "," in written:
        return written.split(",", 1)[0].strip() or None
    words = written.split()
    if words and _INITIAL.match(words[0]):
        rest = [w for w in words if not _INITIAL.match(w)]
        return " ".join(rest) or None
    member = (signature.get("member_name") or "").split()
    return " ".join(member[1:]) if len(member) > 1 else None


def _persons(
    kind: str, row: dict[str, Any], slugs: dict[str, str]
) -> list[FeedPersonDTO]:
    """The signatures as people, named as the member routes name them (the name they go by
    and the surname: ``Hanneke Steen``), else as the paper names them. A person the paper
    lists twice (first and co-signatory, as a minister for two posts) is one person, with
    the first signature."""
    persons = []
    seen: set[str] = set()
    for signature in row.get("persons") or []:
        capacity = signature.get("capacity")
        role = person_role(signature.get("role"), capacity, kind)
        if role is None:
            continue
        who = (
            signature.get("member_key")
            or signature.get("person_id")
            or signature.get("name")
        )
        if who:
            if who in seen:
                continue
            seen.add(who)
        faction = signature.get("faction")
        persons.append(
            FeedPersonDTO(
                key=signature.get("member_key"),
                path_props={"slug": slugs.get(signature.get("member_key") or "")},
                name=signature.get("member_name") or signature.get("name"),
                surname=_surname(signature),
                function=signature.get("function"),
                role=cast(PersonRole, role),
                faction=(
                    FeedFactionDTO(**faction)
                    if faction and capacity == CAPACITY_MEMBER
                    else None
                ),
            )
        )
    return persons


def _official_url(kind: str, props: dict[str, Any]) -> str | None:
    if kind == EVENT_JUDGMENT:
        return judgment_url(props)
    if kind == EVENT_PUBLICATION:
        return instrument_url(props)
    if kind == EVENT_COMMENCEMENT:
        return instrument_url(
            {"bwb_id": props.get("bwb_id")}, on=props.get("valid_from")
        )
    return None


def _judgment(props: dict[str, Any]) -> FeedJudgmentDTO:
    return FeedJudgmentDTO(
        ecli=props.get("ecli"),
        court=props.get("court_code"),
        tier=props.get("tier"),
        court_kind=props.get("court_kind"),
        decision_kind=props.get("decision_kind"),
        procedure=props.get("procedure"),
        decided_on=props.get("date_eff"),
        advocate_general=props.get("advocate_general"),
        advocate_general_role=props.get("advocate_general_role"),
    )


def _vote(props: dict[str, Any], row: dict[str, Any]) -> FeedVoteDTO:
    passed = props.get("passed")
    return FeedVoteDTO(
        chamber=props.get("chamber") or "TK",
        passed=passed,
        outcome=_OUTCOME.get(passed) if isinstance(passed, bool) else None,  # type: ignore[arg-type]
        vote_kind=props.get("vote_kind"),
        tally=props.get("tally") or {},
        method=props.get("method"),
        decision_kind=props.get("decision_kind"),
        coalition=row.get("coalition"),
        coalition_factions=row.get("coalition_factions") or [],
    )


def _commitment(props: dict[str, Any]) -> FeedCommitmentDTO:
    due = props.get("expected_resolution")
    status = props.get("status")
    return FeedCommitmentDTO(
        status=status,
        expected_resolution=due if due and due != NO_DUE_DATE else None,
    )


def _instrument(row: dict[str, Any]) -> FeedInstrumentDTO:
    return FeedInstrumentDTO(
        key=row["key"],
        title=row.get("title"),
        official_url=instrument_url({"bwb_id": row.get("bwb_id")}),
    )


def _publication(props: dict[str, Any], row: dict[str, Any]) -> FeedPublicationDTO:
    series = str(props.get("publication_kind") or "").lower()
    return FeedPublicationDTO(
        series=series if series in ("stb", "stcrt", "trb") else None,  # type: ignore[arg-type]
        year=props.get("publication_year"),
        number=props.get("publication_number"),
        instruments=[_instrument(i) for i in row.get("changed_instruments") or []],
    )


def _commencement(row: dict[str, Any]) -> FeedCommencementDTO:
    instrument = row.get("instrument")
    return FeedCommencementDTO(
        instrument=_instrument(instrument) if instrument else None,
        article_count=(instrument or {}).get("article_count"),
        changed_articles=int(row.get("changed_articles") or 0),
    )


class FeedFacetsDTO(BaseModel):
    """Per dimension the events per value under the other filters, the largest first;
    ``value`` null counts the events without one. An event signed for two factions counts
    for both, so ``faction`` need not add up to ``total``."""

    model_config = ConfigDict(extra="forbid")

    kind: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)
    faction: list[FacetCountDTO] = Field(default_factory=list)
    cabinet: list[FacetCountDTO] = Field(default_factory=list)
    chamber: list[FacetCountDTO] = Field(
        default_factory=list,
        description="``TK``, ``EK``; null for a publication or a commencement.",
    )


class FeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FeedItemDTO]
    next_cursor: str | None = Field(
        None,
        description="Pass as ``cursor`` for the next page; null on the last page.",
    )
    total: int | None = Field(
        None, description="Events under the filters, all pages; null without facets."
    )
    facets: FeedFacetsDTO | None = Field(None, description="Null without facets.")
    partial: bool = Field(
        False,
        description=(
            "Part of the answer is still to come: ``total`` and ``facets`` were asked for "
            "but are still being counted (under a filter not counted before, that takes a "
            "minute or more): null now, ask again; or, with ``searched_from``, the search "
            "for ``q`` did not reach the first event."
        ),
    )
    searched_from: str | None = Field(
        None,
        description=(
            "With ``q`` and no ``since``: the first day searched when the search stopped "
            "before the first event (YYYY-MM-DD). The events found are those from that day "
            "on; ask with ``until`` the day before (and no ``cursor``) for older ones. Null "
            "when every day was searched."
        ),
    )
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source: how current the graph is, as in `GET /api/stats`.",
    )


class FeedDossierCountDTO(BaseModel):
    """The events of one kind in one dossier on a day."""

    model_config = ConfigDict(extra="forbid")

    kind: FeedKind
    number: str
    key: str | None = None
    title: str | None = None
    short_title: str | None = None
    short_title_basis: ShortTitleBasis | None = None
    count: int


class FeedVoteCountDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chamber: Literal["TK", "EK"] = "TK"
    subkind: str | None = Field(
        None,
        description="What was voted on, the ``Zaak.Soort``: ``Motie``, ``Amendement``, "
        "``Wetgeving``, ...",
    )
    outcome: Literal["aangenomen", "verworpen"] | None = None
    count: int


class FeedDayDTO(BaseModel):
    """The events of one day, counted."""

    model_config = ConfigDict(extra="forbid")

    date: str
    total: int = 0
    kinds: list[FacetCountDTO] = Field(default_factory=list)
    dossiers: list[FeedDossierCountDTO] = Field(
        default_factory=list,
        description="Per kind (in the order of a day) and first dossier of an event, "
        "most first within a kind.",
    )
    votes: list[FeedVoteCountDTO] = Field(default_factory=list)


class FeedSummaryResponse(BaseModel):
    """A few days of the feed in one answer."""

    model_config = ConfigDict(extra="forbid")

    since: str
    until: str
    margin: int
    days: list[FeedDayDTO] = Field(
        default_factory=list, description="Every day of the window, newest first."
    )
    items: list[FeedItemDTO] = Field(
        default_factory=list, description="The events shown one by one, feed order."
    )
    items_truncated: bool = Field(
        False, description="More events qualified than ``limit``."
    )
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source: how current the graph is, as in `GET /api/stats`.",
    )

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        *,
        since: dt.date,
        until: dt.date,
        margin: int,
        limit: int,
    ) -> FeedSummaryResponse:
        titles = {d["number"]: d for d in raw.get("dossiers") or []}
        counted = {day["date"]: day for day in raw.get("days") or []}
        days = []
        date = until
        while date >= since:
            day = counted.get(date.isoformat()) or {}
            days.append(
                FeedDayDTO(
                    date=date.isoformat(),
                    total=int(day.get("total") or 0),
                    kinds=[FacetCountDTO(**k) for k in day.get("kinds") or []],
                    dossiers=[
                        _dossier_count(d, titles) for d in day.get("dossiers") or []
                    ],
                    votes=[
                        FeedVoteCountDTO(
                            chamber=v.get("chamber") or "TK",
                            subkind=v.get("subkind"),
                            outcome=_OUTCOME.get(v["passed"])  # type: ignore[arg-type]
                            if isinstance(v.get("passed"), bool)
                            else None,
                            count=v["count"],
                        )
                        for v in day.get("votes") or []
                    ],
                )
            )
            date -= dt.timedelta(days=1)
        rows = raw.get("items") or []
        return cls(
            since=since.isoformat(),
            until=until.isoformat(),
            margin=margin,
            days=days,
            items=[FeedItemDTO.from_row(row) for row in rows[:limit]],
            items_truncated=len(rows) > limit,
        )


def _dossier_count(
    count: dict[str, Any], titles: dict[str, dict[str, Any]]
) -> FeedDossierCountDTO:
    dossier = titles.get(count["number"]) or {}
    short, basis = _dossier_short_title(dossier)
    return FeedDossierCountDTO(
        kind=count["kind"],
        number=count["number"],
        key=dossier.get("key"),
        title=dossier.get("title"),
        short_title=short,
        short_title_basis=basis,
        count=count["count"],
    )


def _dossier_short_title(
    dossier: dict[str, Any],
) -> tuple[str | None, ShortTitleBasis | None]:
    """The short title of a dossier and where it comes from: its title (a budget, the
    parentheses that end a bill's title: ``title``), else the name its bill goes by in
    official data (``official_short``: the citation title in the bill, ``citation``; of
    its case, ``case``; of the one law it changes, ``amended_law``); None without."""
    own = short_title(dossier.get("title"))
    if own:
        return own, "title"
    official = dossier.get("official_short") or {}
    basis = official.get("basis")
    return official.get("title"), basis if basis in get_args(ShortTitleBasis) else None


_ATOM = "http://www.w3.org/2005/Atom"


def _atom_entry(feed: ElementTree.Element, item: FeedItemDTO, site_url: str) -> None:
    entry = ElementTree.SubElement(feed, "entry")
    ElementTree.SubElement(entry, "id").text = f"tag:lawgraph,2026:{item.id}"
    ElementTree.SubElement(entry, "title").text = item.title or item.kind
    ElementTree.SubElement(entry, "updated").text = f"{item.date}T00:00:00Z"
    # the event on Concordans, and its official page
    ElementTree.SubElement(
        entry, "link", rel="alternate", href=f"{site_url}/explore?focus={item.id}"
    )
    related = item.official_url or item.tk_url
    if related:
        ElementTree.SubElement(entry, "link", rel="related", href=related)
    ElementTree.SubElement(entry, "category", term=item.kind)
    for person in item.persons:
        author = ElementTree.SubElement(entry, "author")
        ElementTree.SubElement(author, "name").text = person.name or person.key or "-"
    lines = [line for line in (item.summary, _dossier_line(item)) if line]
    if lines:
        ElementTree.SubElement(entry, "summary").text = "\n".join(lines)


def _dossier_line(item: FeedItemDTO) -> str | None:
    if item.dossier is None:
        return None
    return " ".join(part for part in (item.dossier.number, item.dossier.title) if part)


def atom_feed(
    page: FeedResponse,
    *,
    title: str,
    self_url: str,
    next_url: str | None,
    page_url: str,
    site_url: str,
) -> bytes:
    """*page* as an Atom 1.0 document named *title*: its ``alternate`` link is *page_url*
    (the same view on Concordans, at *site_url*), each entry's the event there."""
    feed = ElementTree.Element("feed", xmlns=_ATOM)
    ElementTree.SubElement(feed, "id").text = self_url
    ElementTree.SubElement(feed, "title").text = title
    newest = page.items[0].date if page.items else "1970-01-01"
    ElementTree.SubElement(feed, "updated").text = f"{newest}T00:00:00Z"
    ElementTree.SubElement(feed, "link", rel="self", href=self_url)
    ElementTree.SubElement(feed, "link", rel="alternate", href=page_url)
    if next_url:
        ElementTree.SubElement(feed, "link", rel="next", href=next_url)
    for item in page.items:
        _atom_entry(feed, item, site_url)
    return ElementTree.tostring(feed, encoding="utf-8", xml_declaration=True)


class AmendmentChainsDTO(BaseModel):
    """The amendments of a period as the Kamer handles them: each chain of papers that
    replace each other once, by its outcome."""

    model_config = ConfigDict(extra="forbid")

    count: int
    aangenomen: int = 0
    verworpen: int = 0
    other: int = Field(
        0, description="Withdrawn, held, postponed, lapsed, or not voted yet."
    )


class FeedPeriodDTO(BaseModel):
    """The events of one month or day."""

    model_config = ConfigDict(extra="forbid")

    period: str = Field(..., description="Its first day: ``2026-09-01`` for September.")
    total: int
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Per kind of event (as ``kind`` of ``GET /api/feed``), those it has.",
    )
    amendment_chains: AmendmentChainsDTO | None = Field(
        None,
        description="The chains of amendment papers (REVISES) of which any paper is an "
        "event under the filters, each once in the period of its first paper, by the "
        "outcome of its last (the latest decision with an outcome on its case, else the "
        "latest); null when ``kind`` leaves the amendments out.",
    )


class FeedPeriodsResponse(BaseModel):
    """The events of the feed per month or day."""

    model_config = ConfigDict(extra="forbid")

    per: Literal["month", "day"]
    since: str | None = None
    until: str | None = None
    periods: list[FeedPeriodDTO] = Field(
        default_factory=list,
        description="Oldest first; a period without events is left out.",
    )
    partial: bool = Field(
        False,
        description="The counts took past the budget of the request, or the events were "
        "never written: ``periods`` is then empty.",
    )
    written_at: str | None = Field(
        None,
        description="When the events were last written (``lawgraph feed-events``): the "
        "counts lag the feed by at most the time since.",
    )
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source: how current the graph is, as in `GET /api/stats`.",
    )
