"""Government responses: ministries, cabinets and their bewindspersonen, commitments."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.committees import PartyRefDTO
from lawgraph.api.schemas.common import END_OF_OFFICE, FacetCountDTO, WithPath
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.ministries import MINISTRY_BY_KEY, POSTS, Source, protocol_rank
from lawgraph.core.tk_records import NO_DUE_DATE

# The status of a commitment is the Toezegging.Status the Tweede Kamer gives it.
COMMITMENT_STATUS_DESCRIPTION = (
    "The status the Tweede Kamer gives the commitment (`Toezegging.Status`), as it writes "
    "it: `Openstaand`, `Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Deels Afgedaan`, "
    "`Vervallen`; null when it gives none."
)
# The kinds of ``core.cabinet_phases.PHASE_KINDS``.
PhaseKind = Literal[
    "formatie", "in_functie", "demissionair", "dubbel_demissionair", "missionair"
]


class MinistryPeriodDTO(BaseModel):
    """A stretch in which the ministry had its name, and where that is known from."""

    model_config = ConfigDict(extra="forbid")

    from_date: str | None = Field(None, description="Null where no source dates it.")
    until: str | None = Field(
        None, description="The last day; null while it has the name, or where unknown."
    )
    successor: MinistryKey | None = None
    basis: str | None = Field(
        None, description="The Staatscourant decree the end rests on (from TOOI)."
    )
    source: Source = Field(
        ...,
        description="``tooi`` (the TOOI value list, since about 2010) or "
        "``rijksoverheid`` (the first post and a handover on the cabinet pages).",
    )
    successor_source: Source | None = Field(
        None,
        description="``curated`` for a succession no source gives (before 2010; "
        "``data/curated/ministries.json``).",
    )


class MinistryDTO(BaseModel):
    """A ministry name of ``data/ministries.json``: a name that came back (Economische
    Zaken) has a period for each time; a former one names its successor and the last day
    it had its name (``successor`` and ``until`` of its last period)."""

    model_config = ConfigDict(extra="forbid")

    key: MinistryKey
    name: str
    abbreviation: str | None = None
    tooi: str | None = Field(None, description="The TOOI code: ``mnre1045``.")
    successor: MinistryKey | None = None
    until: str | None = None
    periods: list[MinistryPeriodDTO] = Field(default_factory=list)


class PersonRefDTO(WithPath):
    """A member named from another node."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "members"

    key: str
    name: str | None = Field(None, description="The name they go by: Sophie Hermans.")


def _slug(person: dict[str, Any], slugs: dict[str, str] | None) -> dict[str, Any]:
    """The props of a member's address: its slug (``load_member_slugs``)."""
    return {"slug": (slugs or {}).get(person.get("key") or "")}


class SourceRefDTO(BaseModel):
    """Where it was read: ``rijksoverheid``, with the page and the day."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: str | None = None
    read_on: str | None = None


class CabinetPhaseDTO(BaseModel):
    """A phase of a cabinet; it ends where the next begins, the last with the cabinet
    (null while it is in office)."""

    model_config = ConfigDict(extra="forbid")

    kind: PhaseKind | None = Field(
        None,
        description="Null for the stretch after elections held while the cabinet was in "
        "office, when the source gives no day of its resignation.",
    )
    from_date: str | None = Field(None, description="The day it began.")
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    label: str | None = Field(None, description="The source's own words.")
    source: SourceRefDTO | None = None


class CoalitionFactionSeatsDTO(BaseModel):
    """A faction's seats in a stretch of a cabinet, and whether it is of the coalition."""

    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(
        None,
        description="The key of the faction; null for a faction of the Eerste Kamer of the "
        "past, which only its name (``abbreviation``) is known by.",
    )
    abbreviation: str | None = None
    seats: int = Field(..., description="Its seats, a vacant one among them.")
    vacant: int = Field(
        0,
        description="Of its seats, those no member held that day (FractieZetelVacature): "
        "between a member who left and the successor's installation.",
    )
    coalition: bool = Field(
        ...,
        description="Its party held a post in the cabinet that day; a faction split off a "
        "coalition party holds none: opposition.",
    )


class SeatEventDTO(BaseModel):
    """What began a stretch: a change of the seats or of the coalition."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        ...,
        description="Eerste Kamer, read from its own pages: ``beëdiging``, ``vertrek``, "
        "``overstap``, ``afsplitsing``, ``hernoeming``, ``samenvoeging``. Tweede Kamer, "
        "derived from the periods of its seats (it gives no reason): ``verkiezing``, "
        "``afsplitsing``, ``overstap``, ``vacature``, ``opvolging``, ``coalitie``.",
    )
    date: str
    words: str | None = Field(
        None,
        description="The source's own words (Eerste Kamer: the headline of its news item, or "
        "the sentence of a faction's page), verbatim; null for the Tweede Kamer, whose kind "
        "is derived.",
    )
    basis: str | None = Field(
        None,
        description="``tekst``: the kind is read from the source's words (show the words); "
        "``afgeleid``: derived from the periods of the seats (show the kind as a label).",
    )
    factions: list[str] = Field(default_factory=list)
    members: list[str] = Field(
        default_factory=list,
        description="Tweede Kamer: member keys; Eerste Kamer: the name the text gives.",
    )


class SeatStretchDTO(BaseModel):
    """A stretch of days in which neither the coalition nor any faction's seats changed."""

    model_config = ConfigDict(extra="forbid")

    from_date: str
    to_date: str
    coalition: int = Field(..., description="The seats of the coalition.")
    opposition: int
    vacant: int = Field(
        0,
        description="Seats that neither a member nor a vacancy of a faction accounts for; a "
        "vacant seat of a faction (FractieZetelVacature) counts among its seats, and for "
        "the coalition or the opposition. `coalition`, `opposition` and `vacant` add up to "
        "the Kamer.",
    )
    factions: list[CoalitionFactionSeatsDTO] = Field(
        default_factory=list, description="The coalition first, then by seats."
    )
    events: list[SeatEventDTO] = Field(
        default_factory=list,
        description="What began the stretch (none for one that began before the cabinet).",
    )
    checked: bool | None = Field(
        None,
        description="Eerste Kamer: whether its term added up (every change's faction known, "
        "no faction below zero, no more than 75 seats; the current term also equal to "
        "today's composition); when false, show the stretch as uncertain. Null for the "
        "Tweede Kamer, whose seats are the source's own.",
    )


class CabinetSeatsResponse(BaseModel):
    """The seats of a cabinet's coalition in each Kamer over its period."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    majority: dict[str, int] = Field(
        ..., description="The seats a majority takes: `TK` 76 of 150, `EK` 38 of 75."
    )
    tk: list[SeatStretchDTO] | None = Field(
        None,
        description="The Tweede Kamer, a stretch per change (a split, a party leaving the "
        "cabinet, a seat changing hands); null for a cabinet that began before 30 November "
        "2006, from when every seat is known.",
    )
    ek: list[SeatStretchDTO] | None = Field(
        None,
        description="The Eerste Kamer, a stretch per change, from the Kiesraad's result of "
        "each election through the changes its own pages tell (``checked`` per term); null "
        "when none of its stretches overlaps the cabinet.",
    )


class CabinetSummaryDTO(WithPath):
    """A cabinet in the list, with its counts."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "cabinets"

    key: str = Field(..., description="``rutte_iv``, ``den_uyl``.")
    name: str = Field(..., description="``kabinet-Rutte IV``.")
    from_date: str | None = Field(None, description="The day of its beëdiging.")
    to_date: str | None = Field(
        None,
        description=END_OF_OFFICE
        + " For a cabinet: the day of the beëdiging of the next one.",
    )
    previous: str | None = Field(None, description="The key of the cabinet before it.")
    prime_minister: PersonRefDTO | None = None
    parties: list[PartyRefDTO] = Field(
        default_factory=list,
        description="The parties of the bewindspersonen sworn in on its first day, the "
        "party with the most first.",
    )
    factions: list[str] = Field(
        default_factory=list, description="The faction keys of its parties."
    )
    demissionary_from: str | None = Field(
        None, description="The start of its first ``demissionair`` phase."
    )
    phases: list[CabinetPhaseDTO] = Field(
        default_factory=list,
        description="Formatie, in functie, demissionair, dubbel demissionair, missionair, "
        "in order.",
    )
    source: SourceRefDTO | None = Field(
        None, description="The Rijksoverheid page it was read from."
    )
    members: int = Field(0, description="The people who held a post in it.")
    bills: int = Field(
        0,
        description="Dossiers of track ``wetsvoorstel`` a bewindspersoon brought in "
        "while it was in office (``initiative`` false, ``cabinet`` this one).",
    )
    commitments: int = Field(0, description="Commitments made while it was in office.")

    @classmethod
    def from_row(
        cls, row: dict[str, Any], slugs: dict[str, str] | None = None
    ) -> CabinetSummaryDTO:
        cabinet = row["cabinet"]
        props = cabinet.get("props") or {}
        prime = row.get("prime_minister")
        return cls(
            key=cabinet["_key"],
            name=props.get("name") or cabinet["_key"],
            from_date=props.get("from_date"),
            to_date=props.get("to_date"),
            previous=props.get("previous"),
            prime_minister=(
                PersonRefDTO(**prime, path_props=_slug(prime, slugs)) if prime else None
            ),
            parties=[PartyRefDTO(**p) for p in props.get("parties") or []],
            factions=props.get("factions") or [],
            demissionary_from=props.get("demissionary_from"),
            phases=[CabinetPhaseDTO(**p) for p in props.get("phases") or []],
            source=props.get("origin"),
            members=int(row.get("members") or 0),
            bills=int(row.get("bills") or 0),
            commitments=int(row.get("commitments") or 0),
        )


class ActingOtherSeatDTO(BaseModel):
    """The seat a stand-in held throughout."""

    model_config = ConfigDict(extra="forbid")

    seat: str
    function: str | None = None


class CabinetPostDTO(BaseModel):
    """One post a person held in the cabinet, with their counts within it."""

    model_config = ConfigDict(extra="forbid")

    member: PersonRefDTO
    post: Post | None = None
    function: str | None = Field(None, description="As Rijksoverheid names the post.")
    also_named: list[str] = Field(
        default_factory=list,
        description="The same post under another name (``minister van Algemene Zaken`` "
        "beside ``Minister-president``).",
    )
    seat: str | None = None
    portfolio: str | None = None
    from_date: str | None = Field(None, description="The day it began.")
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    from_date_source: str | None = Field(
        None, description="The start the source gives; null when it gives none."
    )
    to_date_source: str | None = Field(
        None,
        description="The end the source gives; null when it gives none (the post then "
        "ends with the cabinet, or where the next holder of the seat begins).",
    )
    corrected: list[str] = Field(
        default_factory=list,
        description="Which dates the rules of a seat set, and why.",
    )
    acting: bool = Field(False, description="A stand-in (ad interim).")
    acting_reason: Literal["source", "held_other_seat"] | None = Field(
        None,
        description="Why a post is acting: `source`, the page says so (its words in "
        "`acting_basis`); `held_other_seat`, the holder held another seat throughout and "
        "the post ended where the next holder began (that seat in `acting_other_seat`).",
    )
    acting_basis: str | None = Field(
        None,
        description="What the page says, as it says it: `a.i.`, `tijdelijke voorziening: "
        "…`, `beheer portefeuille overgenomen door de minister van …`.",
    )
    acting_other_seat: ActingOtherSeatDTO | None = Field(
        None, description="For `held_other_seat`: the seat the holder held throughout."
    )
    ministry_source: (
        Literal["page", "tk_signatures", "tk_commitments", "staatscourant"] | None
    ) = Field(
        None,
        description="Where the ministry of the post comes from: `page` (its function "
        "names it), `tk_signatures` (the functions the holder signed Tweede Kamer papers "
        "in), `tk_commitments` (the ministry of their commitments), `staatscourant` (the "
        "ministry that issued the publications naming the post).",
    )
    ministry_missing: Literal["no_source", "ambiguous"] | None = Field(
        None,
        description="Why a post has no ministry: `no_source` (no official source names "
        "one), `ambiguous` (the sources split between ministries).",
    )
    party: PartyRefDTO | None = None
    overlaps_with: list[str] = Field(
        default_factory=list,
        description="The members who held the same seat at the same time, after the "
        "rules: a conflict in the source, not hidden.",
    )
    absent: list[str] | None = Field(
        None, description="``[from, to]`` of a ``tijdelijk afwezig`` in the post."
    )
    source: SourceRefDTO | None = None
    dossiers: int = Field(
        0,
        description="Dossiers with a paper the person signed as bewindspersoon within the "
        "cabinet's period (counted per person, the same on each of their posts).",
    )
    bills: int = Field(0, description="Of those, dossiers of track ``wetsvoorstel``.")
    open_commitments: int = Field(
        0, description="Their commitments made under this cabinet and still open."
    )


class CabinetSeatDTO(BaseModel):
    """One seat and its holders in order of start: a successor is the next post, a
    stand-in a post with ``acting``."""

    model_config = ConfigDict(extra="forbid")

    seat: str = Field(..., description="``ienw/minister``, ``viceminister-president``.")
    post: Post | None = None
    portfolio: str | None = None
    function: str | None = Field(None, description="The name of its first post.")
    posts: list[CabinetPostDTO]


class CabinetMinistryDTO(BaseModel):
    """The seats under one ministry; ``ministry`` null for a seat that names none (the
    viceminister-president, a minister without a named portfolio)."""

    model_config = ConfigDict(extra="forbid")

    ministry: MinistryKey | None = None
    name: str | None = None
    seats: list[CabinetSeatDTO]


def _post_dto(
    item: dict[str, Any], post: dict[str, Any], slugs: dict[str, str] | None
) -> CabinetPostDTO:
    return CabinetPostDTO(
        member=PersonRefDTO(**item["member"], path_props=_slug(item["member"], slugs)),
        post=post.get("post"),
        function=post.get("function"),
        also_named=post.get("also_named") or [],
        seat=post.get("seat"),
        portfolio=post.get("portfolio"),
        from_date=post.get("from_date"),
        to_date=post.get("to_date"),
        from_date_source=post.get("from_date_source"),
        to_date_source=post.get("to_date_source"),
        corrected=post.get("corrected") or [],
        acting=bool(post.get("acting")),
        acting_reason=post.get("acting_reason"),
        acting_basis=post.get("acting_basis"),
        acting_other_seat=post.get("acting_other_seat"),
        ministry_source=post.get("ministry_source"),
        ministry_missing=post.get("ministry_missing"),
        party=post.get("party"),
        overlaps_with=post.get("overlaps_with") or [],
        absent=post.get("absent"),
        source=post.get("source"),
        dossiers=int(item.get("dossiers") or 0),
        bills=int(item.get("bills") or 0),
        open_commitments=int(item.get("open_commitments") or 0),
    )


def _seats(posts: list[CabinetPostDTO]) -> list[CabinetSeatDTO]:
    """The posts grouped by seat: the seats in protocol order (minister-president,
    viceminister-president, minister, minister without portfolio, staatssecretaris),
    the posts in order of start."""
    by_seat: dict[str, list[CabinetPostDTO]] = {}
    for post in posts:
        by_seat.setdefault(post.seat or "", []).append(post)
    post_rank = {post: i for i, post in enumerate(POSTS)}
    seats = []
    for seat, held in by_seat.items():
        held.sort(key=lambda p: (p.from_date or "", p.member.name or ""))
        seats.append(
            CabinetSeatDTO(
                seat=seat,
                post=held[0].post,
                portfolio=held[0].portfolio,
                function=held[0].function,
                posts=held,
            )
        )
    return sorted(
        seats,
        key=lambda s: (
            post_rank.get(s.post or "", len(POSTS)),
            s.posts[0].from_date or "",
            s.seat,
        ),
    )


class CabinetDetailDTO(CabinetSummaryDTO):
    """A cabinet with its bewindspersonen: ministries in protocol order (Algemene Zaken,
    with the minister-president, first), within a ministry the seats (``_seats``). A
    person with two posts is listed under each."""

    ministries: list[CabinetMinistryDTO] = Field(default_factory=list)

    @classmethod
    def from_detail(
        cls, row: dict[str, Any], slugs: dict[str, str] | None = None
    ) -> CabinetDetailDTO:
        members = row.get("members") or []
        summary = CabinetSummaryDTO.from_row({**row, "members": len(members)}, slugs)
        # a seat stands under its ministry: the one its key names (by the name the ministry
        # had when the seat ended: ELI to EZ keeps one seat in one place), else, for a seat
        # whose function names no ministry, that of its last post; each post keeps its own
        # ``ministry`` of its day
        held = [
            (post, _post_dto(item, post, slugs))
            for item in members
            for post in item.get("posts") or []
        ]
        last: dict[str, dict[str, Any]] = {}
        for post, _ in held:
            seat = post.get("seat") or ""
            if seat not in last or (post.get("from_date") or "") >= (
                last[seat].get("from_date") or ""
            ):
                last[seat] = post
        groups: dict[str | None, list[CabinetPostDTO]] = {}
        for post, dto in held:
            seat = post.get("seat") or ""
            named = seat.partition("/")[0]
            ministry = named if named in MINISTRY_BY_KEY else last[seat].get("ministry")
            groups.setdefault(ministry, []).append(dto)
        ministries = [
            CabinetMinistryDTO(
                ministry=MinistryKey(key) if key else None,
                name=MINISTRY_BY_KEY[key].name if key in MINISTRY_BY_KEY else None,
                seats=_seats(posts),
            )
            for key, posts in sorted(groups.items(), key=lambda g: protocol_rank(g[0]))
        ]
        return cls(**summary.model_dump(), ministries=ministries)


class CommitmentDossierDTO(WithPath):
    model_config = ConfigDict(extra="forbid")
    path_collection = "dossiers"

    key: str
    number: str | None = None
    title: str | None = None
    short_title: str | None = Field(
        None, description="The name it goes by, as ``/api/dossiers`` gives it."
    )


class CommitmentActivityDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    date: str | None = None
    number: str | None = None


class CommitmentMemberDTO(PersonRefDTO):
    """Who made the commitment, and the role they made it in as the source writes it."""

    function: str | None = None


class CommitmentDTO(WithPath):
    """A commitment (toezegging) of a bewindspersoon to the Tweede Kamer."""

    model_config = ConfigDict(extra="forbid")
    path_collection = "commitments"

    key: str
    number: str | None = Field(
        None, description="How the Kamer cites it: `TZ202603-130`."
    )
    text: str | None = None
    status: str | None = Field(None, description=COMMITMENT_STATUS_DESCRIPTION)
    date: str | None = Field(None, description="The day it was made.")
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )
    minister_name: str | None = Field(None, description="As the source writes it.")
    member: CommitmentMemberDTO | None = Field(
        None, description="The member who made it; null when no member fits the name."
    )
    post: Post | None = None
    ministry: MinistryKey | None = None
    cabinet: str | None = Field(None, description="The cabinet in office that day.")
    dossiers: list[CommitmentDossierDTO] = Field(default_factory=list)
    activity: CommitmentActivityDTO | None = None

    @classmethod
    def from_row(
        cls, row: dict[str, Any], slugs: dict[str, str] | None = None
    ) -> CommitmentDTO:
        """From a row of ``get_commitments``, and the slugs of the members
        (``load_member_slugs``) for the address of who made it."""
        commitment = row["commitment"]
        props = commitment.get("props") or {}
        member = row.get("member")
        due = props.get("expected_resolution")
        return cls(
            key=commitment["_key"],
            number=props.get("number"),
            text=props.get("text"),
            status=props.get("status"),
            date=props.get("made_on"),
            expected_resolution=due if due and due != NO_DUE_DATE else None,
            minister_name=props.get("minister_name"),
            member=(
                CommitmentMemberDTO(
                    **member,
                    function=props.get("minister_role"),
                    path_props=_slug(member, slugs),
                )
                if member
                else None
            ),
            post=props.get("post"),
            ministry=props.get("ministry"),
            cabinet=props.get("cabinet"),
            dossiers=[
                CommitmentDossierDTO(**d, short_title=short_title(d.get("title")))
                for d in row.get("dossiers") or []
            ],
            activity=row.get("activity"),
        )


class CommitmentFacetsDTO(BaseModel):
    """Per dimension the number of commitments per value under the current filters, each
    dimension counted without its own filter, the largest first: only the values that
    have commitments (a ministry without any is not listed)."""

    model_config = ConfigDict(extra="forbid")

    status: list[FacetCountDTO] = Field(default_factory=list)
    cabinet: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)


class CommitmentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Matching commitments, whatever the page.")
    items: list[CommitmentDTO]
    # null when asked for without them (``facets=false``)
    facets: CommitmentFacetsDTO | None = Field(default_factory=CommitmentFacetsDTO)
