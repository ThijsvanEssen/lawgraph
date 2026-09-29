"""The news feed: dated events of the graph, newest first."""

from __future__ import annotations

from typing import Any, Literal, cast, get_args
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import FacetCountDTO
from lawgraph.api.schemas.government import CommitmentStatus
from lawgraph.api.schemas.stats import DataAsOfDTO
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.feed import (
    DOCUMENT_KINDS,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    ROLE_GOVERNMENT,
    person_role,
)
from lawgraph.core.models import make_node_key, parse_arango_id
from lawgraph.core.official_urls import instrument_url
from lawgraph.core.tk_links import document_page
from lawgraph.core.tk_records import NO_DUE_DATE

# The values of ``core.feed.FEED_KINDS`` and ``PERSON_ROLES``.
FeedKind = Literal[
    "toezegging",
    "wetsvoorstel",
    "nota_van_wijziging",
    "amendement",
    "motie",
    "stemming",
    "publicatie",
    "inwerkingtreding",
    "brief_regering",
]
PersonRole = Literal["indiener", "medeindiener", "bewindspersoon"]
PublicationSeries = Literal["stb", "stcrt", "trb"]

_OUTCOME = {True: "aangenomen", False: "verworpen"}


class FeedNodeDTO(BaseModel):
    """The node an event is: ``/api/nodes/{collection}/{key}`` shows it."""

    model_config = ConfigDict(extra="forbid")

    collection: str
    key: str


class FeedDossierDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    number: str = Field(..., description="The label: ``36600-VII``, a path segment.")
    title: str | None = None
    short_title: str | None = Field(
        None, description="The parentheses that end the title; null without."
    )


class FeedFactionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    short: str | None = Field(None, description="Its abbreviation: ``VVD``.")


class FeedPersonDTO(BaseModel):
    """Someone who signed the event: submitted a paper (``indiener``), signed it with the
    one who did (``medeindiener``), or signed it or made the commitment for the
    government (``bewindspersoon``)."""

    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(None, description="Member key; null when unknown.")
    name: str | None = None
    role: PersonRole
    faction: FeedFactionDTO | None = Field(
        None,
        description="The faction a Kamerlid signed for; null for a bewindspersoon.",
    )


class FeedVoteDTO(BaseModel):
    """The outcome of a ``stemming``."""

    model_config = ConfigDict(extra="forbid")

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


class FeedCommitmentDTO(BaseModel):
    """What a ``toezegging`` stands at."""

    model_config = ConfigDict(extra="forbid")

    status: CommitmentStatus | None = None
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


class FeedItemDTO(BaseModel):
    """One event."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="``collection/key`` of its node: unique.")
    kind: FeedKind
    date: str = Field(..., description="YYYY-MM-DD; the source gives no time of day.")
    title: str | None = None
    summary: str | None = Field(
        None,
        description="The whole text of a commitment, the decision of a vote "
        "(``Aangenomen.``); null for the other kinds.",
    )
    subkind: str | None = Field(
        None,
        description="What the source calls it: the document kind (``Motie (gewijzigd/"
        "nader)``), for a vote what was voted on (``motie``, ``amendement``, "
        "``wetsvoorstel``, ``overig``); null for the other kinds.",
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
    vote: FeedVoteDTO | None = None
    commitment: FeedCommitmentDTO | None = None
    publication: FeedPublicationDTO | None = None
    commencement: FeedCommencementDTO | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> FeedItemDTO:
        kind = row["kind"]
        props = row.get("props") or {}
        collection, key = parse_arango_id(row["id"])
        dossier = row.get("dossier")
        return cls(
            id=row["id"],
            kind=kind,
            date=row["date"],
            title=_title(kind, props, row),
            summary=_summary(kind, props, row),
            subkind=_subkind(kind, props),
            node=FeedNodeDTO(collection=collection, key=key),
            dossier=(
                FeedDossierDTO(**dossier, short_title=short_title(dossier.get("title")))
                if dossier
                else None
            ),
            persons=_persons(row),
            ministry=row.get("ministry"),
            cabinet=row.get("cabinet"),
            official_url=_official_url(kind, props),
            tk_url=document_page(props.get("document_number"))
            if kind in DOCUMENT_KINDS
            else None,
            vote=_vote(props) if kind == EVENT_VOTE else None,
            commitment=_commitment(props) if kind == EVENT_COMMITMENT else None,
            publication=_publication(props, row) if kind == EVENT_PUBLICATION else None,
            commencement=_commencement(row) if kind == EVENT_COMMENCEMENT else None,
        )


def _title(kind: str, props: dict[str, Any], row: dict[str, Any]) -> str | None:
    if kind == EVENT_COMMITMENT:
        return props.get("display_name") or row.get("text")
    if kind == EVENT_COMMENCEMENT:
        return (row.get("instrument") or {}).get("title") or props.get("bwb_id")
    if kind == EVENT_PUBLICATION:
        return props.get("citation_title") or props.get("display_name")
    return props.get("subject") or props.get("title")


def _summary(kind: str, props: dict[str, Any], row: dict[str, Any]) -> str | None:
    if kind == EVENT_COMMITMENT:
        return row.get("text")
    if kind == EVENT_VOTE:
        return props.get("decision_text")
    return None


def _subkind(kind: str, props: dict[str, Any]) -> str | None:
    if kind in DOCUMENT_KINDS or kind == EVENT_VOTE:
        return props.get("kind")
    return None


def _persons(row: dict[str, Any]) -> list[FeedPersonDTO]:
    """The signatures as people: a TK person by the key of its member, the maker of a
    commitment by the member it was matched to."""
    member = row.get("member") or {}
    persons = []
    for signature in row.get("persons") or []:
        role = person_role(signature.get("role"), signature.get("capacity"))
        if role is None:
            continue
        person_id = signature.get("person_id")
        key = signature.get("member_key") or (
            make_node_key(person_id) if person_id else None
        )
        name = signature.get("name")
        if key and key == member.get("key") and member.get("name"):
            name = member["name"]
        faction = signature.get("faction")
        persons.append(
            FeedPersonDTO(
                key=key,
                name=name,
                role=cast(PersonRole, role),
                faction=(
                    FeedFactionDTO(**faction)
                    if faction and role != ROLE_GOVERNMENT
                    else None
                ),
            )
        )
    return persons


def _official_url(kind: str, props: dict[str, Any]) -> str | None:
    if kind == EVENT_PUBLICATION:
        return instrument_url(props)
    if kind == EVENT_COMMENCEMENT:
        return instrument_url(
            {"bwb_id": props.get("bwb_id")}, on=props.get("valid_from")
        )
    return None


def _vote(props: dict[str, Any]) -> FeedVoteDTO:
    passed = props.get("passed")
    return FeedVoteDTO(
        passed=passed,
        outcome=_OUTCOME.get(passed) if isinstance(passed, bool) else None,  # type: ignore[arg-type]
        vote_kind=props.get("vote_kind"),
        tally=props.get("tally") or {},
    )


def _commitment(props: dict[str, Any]) -> FeedCommitmentDTO:
    due = props.get("expected_resolution")
    status = props.get("status")
    return FeedCommitmentDTO(
        status=status if status in get_args(CommitmentStatus) else None,
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
    data_as_of: dict[str, DataAsOfDTO] = Field(
        default_factory=dict,
        description="Per source: how current the graph is, as in `GET /api/stats`.",
    )


_ATOM = "http://www.w3.org/2005/Atom"


def _atom_entry(feed: ElementTree.Element, item: FeedItemDTO, node_url: str) -> None:
    entry = ElementTree.SubElement(feed, "entry")
    ElementTree.SubElement(entry, "id").text = f"tag:lawgraph,2026:{item.id}"
    ElementTree.SubElement(entry, "title").text = item.title or item.kind
    ElementTree.SubElement(entry, "updated").text = f"{item.date}T00:00:00Z"
    link = item.official_url or item.tk_url or node_url.format(**item.node.model_dump())
    ElementTree.SubElement(entry, "link", href=link)
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
    page: FeedResponse, *, self_url: str, next_url: str | None, node_url: str
) -> bytes:
    """*page* as an Atom 1.0 document. *node_url* is the link of an event without an
    official page, with ``{collection}`` and ``{key}`` in it."""
    feed = ElementTree.Element("feed", xmlns=_ATOM)
    ElementTree.SubElement(feed, "id").text = self_url
    ElementTree.SubElement(feed, "title").text = "LawGraph"
    newest = page.items[0].date if page.items else "1970-01-01"
    ElementTree.SubElement(feed, "updated").text = f"{newest}T00:00:00Z"
    ElementTree.SubElement(feed, "link", rel="self", href=self_url)
    if next_url:
        ElementTree.SubElement(feed, "link", rel="next", href=next_url)
    for item in page.items:
        _atom_entry(feed, item, node_url)
    return ElementTree.tostring(feed, encoding="utf-8", xml_declaration=True)
