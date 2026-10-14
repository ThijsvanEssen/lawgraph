"""The news feed: dated events of the graph, newest first."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal, get_args
from xml.etree import ElementTree

from pydantic import Field

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import (
    ArticleChange,
    ChangeEffect,
    FacetCountDTO,
    JudgmentOutcomeFields,
    StrictModel,
    WithPath,
    judgment_outcome_fields,
)
from lawgraph.api.schemas.decisions import CoalitionFactionDTO, CoalitionVoteDTO
from lawgraph.api.schemas.stats import DataAsOfDTO
from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    Chamber,
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
    FeedKind,
    PersonRole,
    person_role,
)
from lawgraph.core.models import parse_node_id
from lawgraph.core.official_urls import instrument_url, judgment_url
from lawgraph.core.publications import (
    PublicationSeries,
    publication_citation,
    publication_series,
)
from lawgraph.core.tk_links import document_page
from lawgraph.core.tk_records import (
    CAPACITY_MEMBER,
    SUBMITTER_FIRST,
    VoteKind,
    due_date,
)
from lawgraph.core.votes import VoteOutcome, vote_outcome
from lawgraph.core.xml import collapse_ws

MatchedField = Literal["title", "dossier_title", "laws"]
ViaRelation = Literal[
    ChangeEffect,
    "proposes",
    "version_of",
    "based_on",
    "refers_to",
    "legislated_in",
]
PeriodUnit = Literal["month", "day"]
ShortTitleBasis = Literal["title", "citation", "case", "amended_law"]


class FeedNodeDTO(StrictModel):
    """The node an event is: ``/api/nodes/{collection}/{key}`` shows it."""

    collection: str
    key: str


class FeedDossierDTO(WithPath):
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
    path_collection = "factions"

    key: str
    short: str | None = Field(None, description="Its abbreviation: ``VVD``.")


class FeedPersonDTO(WithPath):
    """Someone who signed the event: submitted a paper (``indiener``), signed it with the
    one who did (``medeindiener``), or signed it or made the commitment for the
    government (``bewindspersoon``)."""

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


class FeedVoteDTO(StrictModel):
    """The outcome of a ``stemming``."""

    chamber: Chamber = Field(
        "TK",
        description="The chamber that voted; of the Eerste Kamer only the vote that decided "
        "the bill is an event.",
    )
    passed: bool | None = None
    outcome: VoteOutcome | None = None
    vote_kind: VoteKind | None = Field(
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
    coalition_factions: list[CoalitionFactionDTO] = Field(
        default_factory=list,
        description="Of the Tweede Kamer: each coalition faction that cast a seat, with its "
        "choice, most seats first; empty where ``coalition`` is null.",
    )


class FeedCommitmentDTO(StrictModel):
    """What a ``toezegging`` stands at."""

    status: str | None = Field(
        None, description="Of a commitment: its Toezegging.Status (`Openstaand`)."
    )
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )


class FeedInstrumentDTO(StrictModel):
    """A law the event is about."""

    key: str
    title: str | None = None
    official_url: str | None = None


class FeedChangedInstrumentDTO(FeedInstrumentDTO):
    """A law a publication enacts or changes."""

    effect: ChangeEffect = Field(
        ...,
        description="``establishes``: the publication enacted the law (the law names it as "
        "the publication that enacted it); ``amends``, ``introduces`` or ``repeals``: every "
        "change it makes in the law is of that kind (``AMENDS``, ``INTRODUCES``, "
        "``REPEALS`` of its articles or of the law), ``amends`` where they are of more "
        "kinds.",
    )
    article_count: int | None = Field(
        None,
        description="The articles it changes, adds or repeals; of a law it enacts, the "
        "articles of the law.",
    )


_CITATION = "How it is cited: ``Stb. 2026, 94``; null when its series, year or number is unknown."


def _citation(
    series: PublicationSeries | None, year: int | None, number: str | None
) -> str | None:
    return (
        publication_citation(series, year, number)
        if series and year and number
        else None
    )


class FeedPublicationDTO(StrictModel):
    """A ``publicatie`` in the Staatsblad, the Staatscourant or the Tractatenblad."""

    series: PublicationSeries | None = None
    year: int | None = None
    number: str | None = None
    citation: str | None = Field(None, description=_CITATION)
    instruments: list[FeedChangedInstrumentDTO] = Field(
        default_factory=list,
        description="The laws it enacts, then those it amends, introduces or repeals (or "
        "articles of), by title; at most ten.",
    )


class FeedPublicationRefDTO(WithPath):
    """The publication a new version of a law came from."""

    path_collection = "instruments"

    key: str | None = Field(
        None,
        description="Its node key (``stb_2026_187``); null when it is not in the data.",
    )
    series: PublicationSeries | None = None
    year: int | None = None
    number: str | None = None
    citation: str | None = Field(None, description=_CITATION)


class FeedBasisDTO(StrictModel):
    """The law a regulation is issued under: what its preamble ("Gelet op") names."""

    instrument: FeedInstrumentDTO
    kind: str | None = Field(
        None,
        description="The kind of the regulation itself, in lower case as ``/delegated`` "
        "gives it: ``amvb``, ``ministeriele-regeling``.",
    )
    articles: list[str] = Field(
        default_factory=list,
        description="The article numbers of the law it names, in the order of the law.",
    )


class FeedCommencementDTO(StrictModel):
    """An ``inwerkingtreding``: a new version of a law in force from ``date``."""

    instrument: FeedInstrumentDTO | None = None
    article_count: int | None = Field(None, description="The articles of the law.")
    changed_articles: int = Field(
        0, description="The articles with a version that begins that day."
    )
    articles: list[str] = Field(
        default_factory=list,
        description="Their numbers, in the order of the law; at most fifty.",
    )
    new: bool = Field(
        False,
        description="The law itself comes into force: the day is the one it came into "
        "force as enacted (its ``date_in_force``).",
    )
    publication: FeedPublicationRefDTO | None = Field(
        None,
        description="The publication most of those versions came from (their "
        "``origin_publication``): of a new law the one that enacted it; null without.",
    )
    based_on: FeedBasisDTO | None = Field(
        None,
        description="The law the regulation is issued under (``BASED_ON``), the one its "
        "preamble names most articles of; null for a law issued under none.",
    )


class FeedJudgmentDTO(JudgmentOutcomeFields, WithPath):
    """An ``uitspraak``: a judgment or conclusion published on ``date`` (its ``Datum
    publicatie``), of the highest courts unless a ``tier`` is asked for; how it ended."""

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


class FeedHeadlineDTO(StrictModel):
    """The parts a headline is made of; the front end makes the sentence."""

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


class FeedMatchDTO(StrictModel):
    """Where an event holds a word of ``q``."""

    term: str = Field(..., description="The word of ``q``, as it was asked.")
    field: MatchedField = Field(
        ...,
        description="``title``: the title of the event (of a bill its own, which may not "
        "be the ``title`` the item shows: that of its dossier); ``dossier_title``: the "
        "whole title of its first dossier; ``laws``: of a publication, the names of the "
        "laws it enacts or changes (the official title of a law it enacts too). The first "
        "of these that holds it.",
    )


class FeedViaDTO(StrictModel):
    """How an event is tied to the law ``instrument`` (and ``article``) follows."""

    relation: ViaRelation = Field(
        ...,
        description="Of a publication: it ``establishes`` the law, or ``amends``, "
        "``introduces`` or ``repeals`` articles of it; of a paper: it ``proposes`` to "
        "change it; of a new version: of the law itself (``version_of``) or of a "
        "regulation ``based_on`` it; of a judgment: it ``refers_to`` it; of an event of a "
        "dossier (``dossier``): the law or a publication of it was ``legislated_in`` that "
        "dossier, or a paper of it ``proposes`` to change the law.",
    )
    article: str | None = Field(
        None,
        description="The number of the article of the law it touches, the first in the "
        "order of the law; null where it is tied to the law as a whole or by a dossier.",
    )
    dossier: str | None = Field(
        None, description="The label of the dossier it is tied by; null for the others."
    )


class FeedLinkDTO(WithPath):
    """A paper or a commitment an event is tied to."""

    id: str = Field(..., description="``collection/key`` of its node.")
    kind: str | None = Field(
        None,
        description="Of a paper its ``Document.Soort`` (``Motie (gewijzigd/nader)``); "
        "``toezegging`` for a commitment.",
    )
    title: str | None = None
    date: str | None = None
    number: str | None = Field(
        None,
        description="Of a paper its nr. in its dossier (``31``), of a commitment its "
        "number (``TZ202609-124``).",
    )
    dossier: str | None = Field(
        None, description="Of a paper the label of its own dossier (``36764``)."
    )
    surname: str | None = Field(
        None, description="Of a paper its first signatory: ``Kathmann``."
    )


class FeedArticleDTO(WithPath):
    """An article an event is tied to."""

    path_collection = "articles"

    key: str
    bwb_id: str | None = None
    number: str | None = Field(None, description="Its number: ``3:2``.")
    law: str | None = Field(None, description="The citation title of its law.")
    law_short: str | None = Field(
        None, description="The abbreviation its law is cited by: ``Awb``; null without."
    )
    effect: ArticleChange | None = Field(
        None, description="Of an amendment: what it proposes to do with the article."
    )


class FeedItemDTO(WithPath):
    """One event."""

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
    matched: list[FeedMatchDTO] = Field(
        default_factory=list,
        description="With ``q``: per word the event holds, where it holds it; empty "
        "without ``q``.",
    )
    via: FeedViaDTO | None = Field(
        None,
        description="With ``instrument``: how the event is tied to the law; null "
        "without.",
    )
    answers: list[FeedLinkDTO] = Field(
        default_factory=list,
        description="Of a letter of the government: the motions and commitments it "
        "answers (``ANSWERS``); empty for the other kinds.",
    )
    answered_by: list[FeedLinkDTO] = Field(
        default_factory=list,
        description="Of a commitment: the letters that fulfil it (``ANSWERS``); empty "
        "for the other kinds.",
    )
    amends_articles: list[FeedArticleDTO] = Field(
        default_factory=list,
        description="Of an amendment: the articles it proposes to change, add or repeal "
        "(``AMENDS``, ``INTRODUCES``, ``REPEALS``, ``voorgesteld``), in the order of "
        "their law; at most twenty.",
    )
    replaces: FeedLinkDTO | None = Field(
        None,
        description="Of a changed motion or amendment: the paper it replaces "
        '("ter vervanging van nr. 19", ``REVISES``); null for the others.',
    )
    cites: list[FeedArticleDTO] = Field(
        default_factory=list,
        description="Of a judgment: the articles it cites (``REFERS_TO``), the most "
        "mentioned first; at most five.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FeedItemDTO:
        kind = row["kind"]
        props = row.get("props") or {}
        collection, key = parse_node_id(row["id"])
        dossier = row.get("dossier")
        title = _title(kind, props, row)
        persons = _persons(kind, row)
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
                    (p.surname for p in persons if p.role == SUBMITTER_FIRST), None
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
            matched=[FeedMatchDTO(**m) for m in row.get("matched") or []],
            via=FeedViaDTO(**row["via"]) if row.get("via") else None,
            answers=[_link(r) for r in row.get("answers") or [] if r],
            answered_by=[_link(r) for r in row.get("answered_by") or [] if r],
            amends_articles=[_article(r) for r in row.get("amends_articles") or []],
            replaces=_link(row["replaces"]) if row.get("replaces") else None,
            cites=[_article(r) for r in row.get("cites") or []],
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
    return collapse_ws(title) if title else None


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


def _persons(kind: str, row: dict[str, Any]) -> list[FeedPersonDTO]:
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
                path_props={"slug": signature.get("member_slug")},
                name=signature.get("member_name") or signature.get("name"),
                surname=_surname(signature),
                function=signature.get("function"),
                role=role,
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
        **judgment_outcome_fields(props),
    )


def _vote(props: dict[str, Any], row: dict[str, Any]) -> FeedVoteDTO:
    passed = props.get("passed")
    return FeedVoteDTO(
        chamber=props.get("chamber") or "TK",
        passed=passed,
        outcome=vote_outcome(passed),
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
        expected_resolution=due_date(due),
    )


def _instrument_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row["key"],
        "title": row.get("title"),
        "official_url": instrument_url({"bwb_id": row.get("bwb_id")}),
    }


def _instrument(row: dict[str, Any]) -> FeedInstrumentDTO:
    return FeedInstrumentDTO(**_instrument_fields(row))


def _changed(row: dict[str, Any]) -> FeedChangedInstrumentDTO:
    return FeedChangedInstrumentDTO(
        **_instrument_fields(row),
        effect=row["effect"],
        article_count=row.get("article_count"),
    )


def _publication(props: dict[str, Any], row: dict[str, Any]) -> FeedPublicationDTO:
    series = publication_series(props.get("publication_kind"))
    year, number = props.get("publication_year"), props.get("publication_number")
    return FeedPublicationDTO(
        series=series,
        year=year,
        number=number,
        citation=_citation(series, year, number),
        instruments=[_changed(i) for i in row.get("changed_instruments") or []],
    )


def _commencement(row: dict[str, Any]) -> FeedCommencementDTO:
    instrument = row.get("instrument")
    commenced = row.get("commenced") or {}
    basis = commenced.get("based_on")
    in_force = (instrument or {}).get("date_in_force")
    kind = (instrument or {}).get("kind")
    return FeedCommencementDTO(
        instrument=_instrument(instrument) if instrument else None,
        article_count=(instrument or {}).get("article_count"),
        changed_articles=int(row.get("changed_articles") or 0),
        articles=[str(a) for a in commenced.get("articles") or [] if a is not None],
        new=bool(in_force) and in_force == row.get("date"),
        publication=_publication_ref(commenced.get("publication")),
        based_on=(
            FeedBasisDTO(
                instrument=_instrument(basis),
                kind=kind.lower() if isinstance(kind, str) else None,
                articles=[str(a) for a in basis.get("articles") or [] if a is not None],
            )
            if basis
            else None
        ),
    )


def _publication_ref(found: dict[str, Any] | None) -> FeedPublicationRefDTO | None:
    """The publication a version came from, as its ``origin_publication`` names it."""
    if not found:
        return None
    publication = found.get("publication") or {}
    series = publication_series(publication.get("kind"))
    year = publication.get("year") if isinstance(publication.get("year"), int) else None
    number = publication.get("number")
    number = str(number) if number is not None else None
    return FeedPublicationRefDTO(
        key=found.get("key"),
        series=series,
        year=year,
        number=number,
        citation=_citation(series, year, number),
    )


def _link(row: dict[str, Any]) -> FeedLinkDTO:
    """A paper (its light props, subject and first signatory) or a commitment."""
    props = row.get("props") or {}
    collection, _ = parse_node_id(row["id"])
    if collection == COLLECTION_COMMITMENTS:
        return FeedLinkDTO(
            id=row["id"],
            path_props={"number": props.get("number")},
            kind=EVENT_COMMITMENT,
            title=props.get("display_name") or props.get("text"),
            date=row.get("made_on"),
            number=props.get("number"),
            dossier=None,
            surname=None,
        )
    label = props.get("dossier_number")
    suffix = props.get("dossier_suffix")
    signatory = row.get("signatory")
    return FeedLinkDTO(
        id=row["id"],
        path_props={field: props[field] for field in _PATH_PROPS if field in props},
        kind=props.get("kind"),
        title=row.get("subject") or props.get("title") or props.get("display_name"),
        date=props.get("date"),
        number=paper_number(CHAMBER_TK, props),
        dossier=f"{label}-{suffix}" if label and suffix else label,
        surname=_surname(signatory) if isinstance(signatory, dict) else None,
    )


def _article(row: dict[str, Any]) -> FeedArticleDTO:
    return FeedArticleDTO(
        key=row["key"],
        path_props={
            "bwb_id": row.get("bwb_id"),
            "article_number": row.get("article_number"),
        },
        bwb_id=row.get("bwb_id"),
        number=row.get("article_number"),
        law=row.get("law"),
        law_short=row.get("law_short"),
        effect=row.get("effect"),
    )


class FeedFacetsDTO(StrictModel):
    """Per dimension the events per value under the other filters, the largest first;
    ``value`` null counts the events without one. An event signed for two factions counts
    for both, so ``faction`` need not add up to ``total``."""

    kind: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)
    faction: list[FacetCountDTO] = Field(default_factory=list)
    cabinet: list[FacetCountDTO] = Field(default_factory=list)
    chamber: list[FacetCountDTO] = Field(
        default_factory=list,
        description="``TK``, ``EK``; null for a publication or a commencement.",
    )
    coalition: list[FacetCountDTO] = Field(
        default_factory=list,
        description="What the coalition did on the votes of the Tweede Kamer: "
        "``together``, ``split`` (with ``wissel``), ``wissel``, ``decisive``; a vote "
        "counts for each that holds, an event without a coalition vote for none.",
    )


class FeedResponse(StrictModel):
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
            "for ``q`` or ``faction`` did not reach the first event."
        ),
    )
    searched_from: str | None = Field(
        None,
        description=(
            "With ``q`` or ``faction`` and no ``since``: the first day searched when the "
            "search stopped before the first event (YYYY-MM-DD). The events found are "
            "those from that day on; ask with ``until`` the day before (and no "
            "``cursor``) for older ones. Null when every day was searched."
        ),
    )
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source: how current the graph is, as in `GET /api/stats`.",
    )


class FeedDossierCountDTO(StrictModel):
    """The events of one kind in one dossier on a day."""

    kind: FeedKind
    number: str
    key: str | None = None
    title: str | None = None
    short_title: str | None = None
    short_title_basis: ShortTitleBasis | None = None
    count: int


class FeedVoteCountDTO(StrictModel):
    chamber: Chamber = "TK"
    subkind: str | None = Field(
        None,
        description="What was voted on, the ``Zaak.Soort``: ``Motie``, ``Amendement``, "
        "``Wetgeving``, ...",
    )
    outcome: VoteOutcome | None = None
    count: int


class FeedDayDTO(StrictModel):
    """The events of one day, counted."""

    date: str
    total: int = 0
    kinds: list[FacetCountDTO] = Field(default_factory=list)
    dossiers: list[FeedDossierCountDTO] = Field(
        default_factory=list,
        description="Per kind (in the order of a day) and first dossier of an event, "
        "most first within a kind.",
    )
    votes: list[FeedVoteCountDTO] = Field(default_factory=list)


class FeedSummaryResponse(StrictModel):
    """A few days of the feed in one answer."""

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
                            outcome=vote_outcome(v.get("passed")),
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


class AmendmentChainsDTO(StrictModel):
    """The amendments of a period as the Kamer handles them: each chain of papers that
    replace each other once, by its outcome."""

    count: int
    aangenomen: int = 0
    verworpen: int = 0
    other: int = Field(
        0, description="Withdrawn, held, postponed, lapsed, or not voted yet."
    )


class FeedPeriodDTO(StrictModel):
    """The events of one month or day."""

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


class FeedPeriodsResponse(StrictModel):
    """The events of the feed per month or day."""

    per: PeriodUnit
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
