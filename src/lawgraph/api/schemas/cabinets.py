"""Cabinet responses: a cabinet, its bewindspersonen by ministry and seat, and the seats of
its coalition."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.common import END_OF_OFFICE, PathSource, StrictModel, WithPath
from lawgraph.api.schemas.members import PersonRefDTO
from lawgraph.api.schemas.parties import PartyRefDTO
from lawgraph.core.cabinet_phases import PhaseKind
from lawgraph.core.cabinet_posts import ActingReason
from lawgraph.core.ministries import MINISTRY_BY_KEY, POSTS, protocol_rank
from lawgraph.core.post_ministries import MinistryMissing, MinistrySource


class SourceRefDTO(StrictModel):
    """Where it was read: ``rijksoverheid``, with the page and the day."""

    name: str | None = None
    url: str | None = None
    read_on: str | None = None


class CabinetPhaseDTO(StrictModel):
    """A phase of a cabinet; it ends where the next begins, the last with the cabinet
    (null while it is in office)."""

    kind: PhaseKind | None = Field(
        None,
        description="Null for the stretch after elections held while the cabinet was in "
        "office, when the source gives no day of its resignation.",
    )
    from_date: str | None = Field(None, description="The day it began.")
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    label: str | None = Field(None, description="The source's own words.")
    source: SourceRefDTO | None = None


class CoalitionFactionSeatsDTO(StrictModel):
    """A faction's seats in a stretch of a cabinet, and whether it is of the coalition."""

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


class SeatEventDTO(StrictModel):
    """What began a stretch: a change of the seats or of the coalition."""

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


class SeatStretchDTO(StrictModel):
    """A stretch of days in which neither the coalition nor any faction's seats changed."""

    from_date: str
    to_date: str
    coalition: int = Field(
        ...,
        description="The seats of the coalition's parties, their vacant ones included (a "
        "vacant seat of a faction, FractieZetelVacature, is still its faction's): what "
        "a majority is counted in.",
    )
    opposition: int = Field(
        ..., description="The seats of the other parties, their vacant ones included."
    )
    vacant: int = Field(
        0,
        description="Every seat no member held: the vacant seats of the factions and any "
        "seat neither a member nor a vacancy accounts for. The seats held are the Kamer's "
        "but these.",
    )
    coalition_vacant: int = Field(
        0, description="Of `coalition`, the seats no member held (Tweede Kamer)."
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


class CabinetSeatsResponse(StrictModel):
    """The seats of a cabinet's coalition in each Kamer over its period."""

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

    path_source = PathSource("cabinets")

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
    def fields_of(cls, row: dict[str, Any]) -> dict[str, Any]:
        cabinet = row["cabinet"]
        props = cabinet.get("props") or {}
        prime = row.get("prime_minister")
        return {
            "key": cabinet["key"],
            "name": props.get("name") or cabinet["key"],
            "from_date": props.get("from_date"),
            "to_date": props.get("to_date"),
            "previous": props.get("previous"),
            "prime_minister": PersonRefDTO.from_row(prime) if prime else None,
            "parties": [PartyRefDTO(**p) for p in props.get("parties") or []],
            "factions": props.get("factions") or [],
            "demissionary_from": props.get("demissionary_from"),
            "phases": [CabinetPhaseDTO(**p) for p in props.get("phases") or []],
            "source": props.get("origin"),
            "members": int(row.get("members") or 0),
            "bills": int(row.get("bills") or 0),
            "commitments": int(row.get("commitments") or 0),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CabinetSummaryDTO:
        return cls(**CabinetSummaryDTO.fields_of(row))


class ActingOtherSeatDTO(StrictModel):
    """The seat a stand-in held throughout."""

    seat: str
    function: str | None = None


class CabinetPostDTO(StrictModel):
    """One post a person held in the cabinet, with their counts within it."""

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
    acting_reason: ActingReason | None = Field(
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
    ministry_source: MinistrySource | None = Field(
        None,
        description="Where the ministry of the post comes from: `page` (its function "
        "names it), `tk_signatures` (the functions the holder signed Tweede Kamer papers "
        "in), `tk_commitments` (the ministry of their commitments), `staatscourant` (the "
        "ministry that issued the publications naming the post).",
    )
    ministry_missing: MinistryMissing | None = Field(
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


class CabinetSeatDTO(StrictModel):
    """One seat and its holders in order of start: a successor is the next post, a
    stand-in a post with ``acting``."""

    seat: str = Field(..., description="``ienw/minister``, ``viceminister-president``.")
    post: Post | None = None
    portfolio: str | None = None
    function: str | None = Field(None, description="The name of its first post.")
    posts: list[CabinetPostDTO]


class CabinetMinistryDTO(StrictModel):
    """The seats under one ministry; ``ministry`` null for a seat that names none (the
    viceminister-president, a minister without a named portfolio)."""

    ministry: MinistryKey | None = None
    name: str | None = None
    seats: list[CabinetSeatDTO]


def _post_dto(item: dict[str, Any], post: dict[str, Any]) -> CabinetPostDTO:
    return CabinetPostDTO(
        member=PersonRefDTO.from_row(item["member"]),
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
    def from_detail(cls, row: dict[str, Any]) -> CabinetDetailDTO:
        members = row.get("members") or []
        # a seat stands under its ministry: the one its key names (by the name the ministry
        # had when the seat ended: ELI to EZ keeps one seat in one place), else, for a seat
        # whose function names no ministry, that of its last post; each post keeps its own
        # ``ministry`` of its day
        held = [
            (post, _post_dto(item, post))
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
        return cls(
            **CabinetSummaryDTO.fields_of({**row, "members": len(members)}),
            ministries=ministries,
        )
