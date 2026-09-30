"""Queries behind the committee, member and faction endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_AUTHORED,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_REPEALS,
    RELATION_VOTED,
)
from lawgraph.core.tk_records import VOTE_KIND_MEMBER
from lawgraph.db import ArangoStore

# A committee whose name is just a GUID carries no usable identity.
_GUID_NAME = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

_CURRENT_MEMBERSHIP = (
    "FILTER NOT HAS(e.meta, 'to_date') OR e.meta.to_date == null"
    " OR e.meta.to_date >= @today"
    # a seat of the Eerste Kamer ends where a snapshot no longer shows it
    "\n                FILTER e.meta.observed_until == null"
)

# The chamber a faction, committee or member list is of: the Eerste Kamer's carry
# ``chamber`` ``EK`` (``normalize eerstekamer-composition``), the Tweede Kamer's none.
CHAMBER_EK = "EK"


def _chamber(var: str, chamber: str) -> str:
    """AQL: *var* (a faction or committee) is of *chamber* (``TK`` or ``EK``)."""
    return (
        f'{var}.props.chamber {"==" if chamber == CHAMBER_EK else "!="} "{CHAMBER_EK}"'
    )


def get_committees(store: ArangoStore, *, chamber: str = "TK") -> list[dict[str, Any]]:
    """Every committee of *chamber* with a name, by name; of the Eerste Kamer only those
    the last snapshot shows. ``props.active_dossier_count`` is what ``semantic
    graph-list-stats`` counted."""
    aql = f"""
    FOR committee IN {COLLECTION_COMMITTEES}
        FILTER {_chamber("committee", chamber)}
        FILTER committee.props.observed_until == null
        LET name = committee.props.name
        FILTER name != null AND name != ""
        FILTER NOT REGEX_TEST(name, "{_GUID_NAME}", true)
        SORT name ASC, committee._key ASC
        RETURN committee
    """
    return list(store.query(aql))


# A dossier is open until ``semantic tk-dossier-outcomes`` closed it (as
# ``/dossiers?status=open``).
_DOSSIER_CLOSED = "dossier.props.closed == true"


def get_committee_detail(
    store: ArangoStore,
    slug: str,
    *,
    current_only: bool = True,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """One committee with its members and a page of the dossiers it leads.

    Accepts the committee's ``slug`` or its ``_key``. With *current_only* the
    members are those whose seat has no end date, or an end date still ahead.
    *status* (``open`` or ``closed``) keeps the dossiers of that state, newest
    first; ``dossier_total`` counts them all.
    """
    aql = f"""
    FOR committee IN {COLLECTION_COMMITTEES}
        FILTER committee.props.slug == @slug OR LOWER(committee._key) == @slug
        LIMIT 1

        LET members = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == committee._id AND e.relation == @member_of
                {_CURRENT_MEMBERSHIP if current_only else ""}
                LET member = DOCUMENT(e._from)
                FILTER member != null
                SORT member.props.name ASC
                RETURN MERGE(member, {{
                    from_date: e.meta.from_date,
                    to_date: e.meta.to_date,
                    role: e.meta.role,
                    observed_from: e.meta.observed_from,
                    observed_until: e.meta.observed_until
                }})
        )

        LET dossier_ids = UNIQUE(
            FOR led IN {COLLECTION_EDGES}
                FILTER led._to == committee._id AND led.relation == @led_by
                FOR subject IN {COLLECTION_EDGES}
                    FILTER subject._from == led._from
                        AND subject.relation == @about
                    FILTER STARTS_WITH(subject._to, "{COLLECTION_DOSSIERS}/")
                    RETURN subject._to
        )
        LET led_dossiers = (
            FOR dossier_id IN dossier_ids
                LET dossier = DOCUMENT(dossier_id)
                FILTER dossier != null
                RETURN {{ dossier: dossier, closed: {_DOSSIER_CLOSED} }}
        )
        LET matching = (
            FOR row IN led_dossiers
                FILTER @status == null OR (@status == "closed") == row.closed
                RETURN row.dossier
        )
        LET dossiers = (
            FOR dossier IN matching
                SORT dossier.props.opened_on DESC, dossier._key ASC
                LIMIT @offset, @limit
                RETURN dossier
        )

        RETURN MERGE(committee, {{
            members: members,
            dossiers: dossiers,
            dossier_total: LENGTH(matching)
        }})
    """
    bind: dict[str, Any] = {
        "slug": slug.lower(),
        "status": status,
        "limit": limit,
        "offset": offset,
        "member_of": RELATION_MEMBER_OF,
        "led_by": RELATION_LED_BY,
        "about": RELATION_ABOUT,
    }
    if current_only:
        bind["today"] = dt.date.today().isoformat()
    for doc in store.query(aql, bind):
        return doc
    return None


def get_committee_activities(
    store: ArangoStore, slug: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any] | None:
    """A page of the activities a committee leads, newest first; None when unknown.

    Accepts the committee's ``slug`` or its ``_key``. Returns ``{total, items}``.
    """
    aql = f"""
    FOR committee IN {COLLECTION_COMMITTEES}
        FILTER committee.props.slug == @slug OR LOWER(committee._key) == @slug
        LIMIT 1
        LET led_activities = (
            FOR led IN {COLLECTION_EDGES}
                FILTER led._to == committee._id AND led.relation == @led_by
                LET activity = DOCUMENT(led._from)
                FILTER activity != null
                RETURN activity
        )
        RETURN {{
            total: LENGTH(led_activities),
            items: (
                FOR activity IN led_activities
                    SORT activity.props.date DESC, activity._key ASC
                    LIMIT @offset, @limit
                    RETURN {{
                        id: activity._id,
                        key: activity._key,
                        date: activity.props.date,
                        kind: activity.props.kind,
                        agenda_title: activity.props.agenda_title,
                        status: activity.props.status,
                        dossier_numbers: activity.props.dossier_numbers OR []
                    }}
            )
        }}
    """
    bind = {
        "slug": slug.lower(),
        "limit": limit,
        "offset": offset,
        "led_by": RELATION_LED_BY,
    }
    for row in store.query(aql, bind):
        return cast(dict[str, Any], row)
    return None


# The name a member goes by; a TK person without one: the name Rijksoverheid gives.
_MEMBER_NAME = (
    "member.props.name OR member.props.known_as OR member.props.government_name"
)


def get_members(
    store: ArangoStore,
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    include_all: bool = False,
    government: bool = False,
    cabinet: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Members of parliament, in name order; never a record without a name.

    Restricted to people who ever held a seat; *include_all* also returns the
    ministers and other people the TK Persoon endpoint exposes. *government* keeps
    those who held a post in a cabinet, *cabinet* those who held one in that cabinet
    (both whether they sat in parliament or not). *party* matches the current party or
    any abbreviation, name or alias in the member's faction timeline.
    """
    filters: list[str] = [f"({_MEMBER_NAME}) NOT IN [null, '']"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}

    if government:
        filters.append("LENGTH(member.props.government_functions) > 0")
    if cabinet:
        filters.append("@cabinet IN member.props.government_functions[*].cabinet_key")
        bind["cabinet"] = cabinet
    if not (include_all or government or cabinet):
        filters.append("LENGTH(member.props.faction_memberships) > 0")
    if party:
        filters.append(
            "(LOWER(member.props.party) == @party"
            " OR LENGTH(FOR m IN (member.props.faction_memberships OR [])"
            "    FILTER LOWER(m.abbreviation) == @party"
            "        OR LOWER(m.name) == @party"
            "        OR @party IN (FOR a IN (m.aliases OR []) RETURN LOWER(a))"
            "    LIMIT 1 RETURN 1) > 0)"
        )
        bind["party"] = party.strip().lower()
    if q:
        filters.append(f"CONTAINS(LOWER({_MEMBER_NAME}), @q)")
        bind["q"] = q.strip().lower()

    where = ("FILTER " + " AND ".join(filters)) if filters else ""
    aql = f"""
    FOR member IN {COLLECTION_MEMBERS}
        {where}
        LET seated = LENGTH(
            FOR m IN (member.props.faction_memberships OR [])
                FILTER m.to_date == null
                LIMIT 1 RETURN 1
        ) > 0
        FILTER @active == null OR seated == @active
        SORT {_MEMBER_NAME} ASC, member._key
        LIMIT @offset, @limit
        RETURN member
    """
    return list(store.query(aql, bind))


def get_ek_members(
    store: ArangoStore,
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """The members of the Eerste Kamer (``props.ek``), in name order: those the last
    snapshot shows (*active*), those it no longer does, or both. *party* matches the
    abbreviation of their faction."""
    filters = ["member.props.ek != null"]
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}
    if party:
        filters.append("LOWER(member.props.ek.abbreviation) == @party")
        bind["party"] = party.strip().lower()
    if q:
        filters.append(
            f"CONTAINS(LOWER({_MEMBER_NAME}), @q) OR CONTAINS(LOWER(member.props.ek.name), @q)"
        )
        bind["q"] = q.strip().lower()
    aql = f"""
    FOR member IN {COLLECTION_MEMBERS}
        FILTER {" AND ".join(f"({f})" for f in filters)}
        LET seated = member.props.ek.observed_until == null
        FILTER @active == null OR seated == @active
        SORT {_MEMBER_NAME} ASC, member._key
        LIMIT @offset, @limit
        RETURN member
    """
    return list(store.query(aql, bind))


def get_factions(
    store: ArangoStore,
    *,
    active: bool | None = None,
    q: str | None = None,
    chamber: str = "TK",
) -> list[dict[str, Any]]:
    """Every parliamentary party of *chamber* with its member count (of the Eerste Kamer:
    the members the last snapshot shows), seated ones first."""
    bind: dict[str, Any] = {"member_of": RELATION_MEMBER_OF}
    filters = [
        "faction.props.name != null AND faction.props.name != ''",
        _chamber("faction", chamber),
    ]
    if active is not None:
        filters.append("faction.props.active == @active")
        bind["active"] = active
    if q:
        filters.append(
            "CONTAINS(LOWER(faction.props.name), @q) OR CONTAINS("
            "LOWER(faction.props.abbreviation != null ? faction.props.abbreviation : ''), @q)"
        )
        bind["q"] = q.strip().lower()

    aql = f"""
    LET counts = MERGE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @member_of
            FILTER STARTS_WITH(e._to, "{COLLECTION_FACTIONS}/")
            FILTER e.meta.observed_until == null
            COLLECT faction_id = e._to WITH COUNT INTO total
            RETURN {{ [faction_id]: total }}
    )
    FOR faction IN {COLLECTION_FACTIONS}
        {chr(10).join(f"        FILTER {f}" for f in filters)}
        SORT faction.props.active DESC, faction.props.abbreviation ASC,
             faction.props.name ASC
        RETURN MERGE(faction, {{
            member_count: counts[faction._id] != null ? counts[faction._id] : 0
        }})
    """
    return list(store.query(aql, bind))


def get_seats_on(store: ArangoStore, day: str) -> dict[str, int]:
    """Faction key -> the seats its members held on *day* (YYYY-MM-DD), from their
    ``faction_memberships``: a member is one seat of a faction, whatever their role."""
    aql = f"""
    FOR member IN {COLLECTION_MEMBERS}
        FOR m IN (member.props.faction_memberships OR [])
            FILTER m.from_date != null AND m.from_date <= @day
            FILTER m.to_date == null OR m.to_date >= @day
            COLLECT faction = m.faction_key INTO held = member._key
            RETURN {{faction, seats: COUNT_DISTINCT(held)}}
    """
    return {row["faction"]: row["seats"] for row in store.query(aql, {"day": day})}


def get_member_votes(
    store: ArangoStore, member_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """How a member voted, newest first.

    Two kinds of vote reach a member. A roll-call names every member, so the
    VOTED edge starts at the member. Any other vote is cast by the faction,
    and counts for the member only while they belonged to it — which is what
    ``faction_memberships`` dates. ``party`` is the party they sat for at the
    time, so historic votes keep their colour after a switch.
    """
    aql = f"""
    LET member = DOCUMENT(@member_id)
    FILTER member != null
    LET memberships = member.props.faction_memberships != null
        ? member.props.faction_memberships : []

    LET own = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @member_id AND e.relation == @voted
            LET decision = DOCUMENT(e._to)
            FILTER decision != null
            RETURN {{
                decision: decision,
                choice: e.meta.choice,
                seats: e.meta.seats,
                party: member.props.party,
                faction_key: null
            }}
    )
    LET by_faction = (
        FOR m IN memberships
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == m.faction_id AND e.relation == @voted
                LET decision = DOCUMENT(e._to)
                FILTER decision != null AND decision.props.date != null
                FILTER decision.props.vote_kind != @roll_call
                FILTER (m.from_date == null OR m.from_date <= decision.props.date)
                   AND (m.to_date == null OR m.to_date >= decision.props.date)
                RETURN {{
                    decision: decision,
                    choice: e.meta.choice,
                    seats: e.meta.seats,
                    party: m.abbreviation != null ? m.abbreviation : m.name,
                    faction_key: m.faction_key
                }}
    )
    FOR row IN APPEND(own, by_faction)
        SORT row.decision.props.date DESC
        LIMIT @limit
        RETURN {{
            decision_id: row.decision._id,
            decision_key: row.decision._key,
            external_id: row.decision.props.decision_id,
            date: row.decision.props.date,
            subject: row.decision.props.subject,
            passed: row.decision.props.passed,
            choice: row.choice,
            seats: row.seats,
            party: row.party,
            faction_key: row.faction_key
        }}
    """
    bind = {
        "member_id": member_id,
        "limit": limit,
        "voted": RELATION_VOTED,
        "roll_call": VOTE_KIND_MEMBER,
    }
    return list(store.query(aql, bind))


def get_actor_touched_instruments(
    store: ArangoStore, actor_id: str, *, limit: int = 10
) -> list[dict[str, Any]]:
    """The laws a member most often proposes changes to.

    Walks member → AUTHORED → document → AMENDS/INTRODUCES/REPEALS → article
    → PART_OF → instrument, and counts the distinct documents per instrument.
    The instrument document is only fetched for the rows that survive the
    limit.
    """
    aql = f"""
    FOR authored IN {COLLECTION_EDGES}
        FILTER authored._from == @actor_id AND authored.relation == @authored
        LET document_id = authored._to
        FOR change IN {COLLECTION_EDGES}
            FILTER change._from == document_id
                AND change.relation IN @changes
            FOR part IN {COLLECTION_EDGES}
                FILTER part._from == change._to AND part.relation == @part_of
                FILTER STARTS_WITH(part._to, "{COLLECTION_INSTRUMENTS}/")
                COLLECT instrument_id = part._to INTO touching = document_id
                LET document_count = LENGTH(UNIQUE(touching))
                SORT document_count DESC
                LIMIT @limit
                LET instrument = DOCUMENT(instrument_id)
                FILTER instrument != null
                RETURN {{
                    id: instrument_id,
                    key: instrument._key,
                    display_name: instrument.props.display_name,
                    title: instrument.props.title,
                    short_title: instrument.props.short_title,
                    citation_title: instrument.props.citation_title,
                    bwb_id: instrument.props.bwb_id,
                    celex: instrument.props.celex,
                    count: document_count
                }}
    """
    bind = {
        "actor_id": actor_id,
        "limit": limit,
        "authored": RELATION_AUTHORED,
        "part_of": RELATION_PART_OF,
        "changes": [RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS],
    }
    return list(store.query(aql, bind))


def get_actor_dossiers(
    store: ArangoStore,
    actor_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of the dossiers a member or a faction authored documents in.

    Walks member -> ``AUTHORED`` -> document (or case) -> ``PART_OF`` -> dossier, directly
    or through a case. A faction has no ``AUTHORED`` edges of its own: it counts the
    documents its members signed while they belonged to it (``faction_memberships``, as
    for their votes). Each dossier carries the distinct ``AUTHORED`` roles and the number
    of documents; newest opened first. Returns ``{total, items}``.
    """
    is_faction = actor_id.startswith(f"{COLLECTION_FACTIONS}/")
    if is_faction:
        head = f"""
        FOR seat IN {COLLECTION_EDGES}
            FILTER seat._to == @actor_id AND seat.relation == @member_of
            LET member = DOCUMENT(seat._from)
            FILTER member != null
            LET periods = (
                FOR m IN (member.props.faction_memberships OR [])
                    FILTER m.faction_id == @actor_id
                    RETURN m
            )
            FOR authored IN {COLLECTION_EDGES}
                FILTER authored._from == member._id AND authored.relation == @authored
        """
        in_period = """
            FILTER LENGTH(
                FOR m IN periods
                    LET date = DOCUMENT(authored._to).props.date
                    FILTER date != null
                    FILTER (m.from_date == null OR m.from_date <= date)
                        AND (m.to_date == null OR m.to_date >= date)
                    LIMIT 1 RETURN 1
            ) > 0
        """
    else:
        head = f"""
        FOR authored IN {COLLECTION_EDGES}
            FILTER authored._from == @actor_id AND authored.relation == @authored
        """
        in_period = ""

    aql = f"""
    LET rows = (
        {head}
            LET direct = (
                FOR p IN {COLLECTION_EDGES}
                    FILTER p._from == authored._to AND p.relation == @part_of
                    FILTER STARTS_WITH(p._to, "{COLLECTION_DOSSIERS}/")
                    RETURN p._to
            )
            LET via_case = (
                FOR p1 IN {COLLECTION_EDGES}
                    FILTER p1._from == authored._to AND p1.relation == @part_of
                    FILTER STARTS_WITH(p1._to, "{COLLECTION_CASES}/")
                    FOR p2 IN {COLLECTION_EDGES}
                        FILTER p2._from == p1._to AND p2.relation == @part_of
                        FILTER STARTS_WITH(p2._to, "{COLLECTION_DOSSIERS}/")
                        RETURN p2._to
            )
            LET dossier_ids = UNIQUE(APPEND(direct, via_case))
            FILTER LENGTH(dossier_ids) > 0
            {in_period}
            FOR dossier_id IN dossier_ids
                RETURN {{
                    dossier_id: dossier_id,
                    document_id: authored._to,
                    role: authored.meta.role,
                    function: authored.meta.function,
                    capacity: authored.meta.capacity
                }}
    )
    LET grouped = (
        FOR row IN rows
            COLLECT dossier_id = row.dossier_id INTO group = row
            LET dossier = DOCUMENT(dossier_id)
            FILTER dossier != null
            RETURN {{
                dossier: dossier,
                roles: (
                    FOR role IN UNIQUE(group[*].role)
                        FILTER role != null AND role != ""
                        SORT role
                        RETURN role
                ),
                functions: (
                    FOR function IN UNIQUE(group[*].function)
                        FILTER function != null AND function != ""
                        SORT function
                        RETURN function
                ),
                capacities: (
                    FOR capacity IN UNIQUE(group[*].capacity)
                        FILTER capacity != null
                        SORT capacity
                        RETURN capacity
                ),
                document_count: LENGTH(UNIQUE(group[*].document_id))
            }}
    )
    RETURN {{
        total: LENGTH(grouped),
        items: (
            FOR row IN grouped
                SORT row.dossier.props.opened_on DESC, row.dossier._key ASC
                LIMIT @offset, @limit
                RETURN row
        )
    }}
    """
    bind: dict[str, Any] = {
        "actor_id": actor_id,
        "limit": limit,
        "offset": offset,
        "authored": RELATION_AUTHORED,
        "part_of": RELATION_PART_OF,
    }
    if is_faction:
        bind["member_of"] = RELATION_MEMBER_OF
    rows = list(store.query(aql, bind))
    return cast(dict[str, Any], rows[0]) if rows else {"total": 0, "items": []}


def get_ek_faction_votes(
    store: ArangoStore,
    abbreviation: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """How a faction of the Eerste Kamer voted, by its name as the list of votes writes it
    (*abbreviation*): ``{total, counts, items}``, newest first. ``counts`` per choice
    (``voor``, ``tegen``, ``aantekening gevraagd``) over every vote that names it."""
    aql = f"""
    LET voted = (
        FOR d IN {COLLECTION_DECISIONS}
            FILTER d.props.chamber == @ek
            FILTER @from == null OR d.props.date >= @from
            FILTER @to == null OR d.props.date <= @to
            LET choice = @name IN (d.props.factions_for OR []) ? "voor"
                : @name IN (d.props.factions_against OR []) ? "tegen"
                : @name IN (d.props.factions_noted OR []) ? "aantekening gevraagd"
                : null
            FILTER choice != null
            RETURN {{ d, choice }}
    )
    LET counts = MERGE(
        FOR v IN voted
            COLLECT choice = v.choice WITH COUNT INTO n
            RETURN {{ [choice]: n }}
    )
    LET items = (
        FOR v IN voted
            SORT v.d.props.date DESC, v.d._key
            LIMIT @offset, @limit
            RETURN {{
                decision_id: v.d._id,
                decision_key: v.d._key,
                date: v.d.props.date,
                subject: v.d.props.subject,
                dossier_numbers: v.d.props.dossier_numbers OR [],
                result: v.d.props.result,
                method: v.d.props.method,
                bill_decision: v.d.props.bill_decision,
                choice: v.choice
            }}
    )
    RETURN {{ total: LENGTH(voted), counts, items }}
    """
    bind = {
        "ek": CHAMBER_EK,
        "name": abbreviation,
        "from": date_from,
        "to": date_to,
        "limit": limit,
        "offset": offset,
    }
    row = next(iter(store.query(aql, bind)), None)
    return row or {"total": 0, "counts": {}, "items": []}
