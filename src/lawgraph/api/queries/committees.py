"""Queries behind the committee, member and faction endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
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
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.tk_records import VOTE_KIND_MEMBER
from lawgraph.db import ArangoStore

# A committee whose name is just a GUID carries no usable identity.
_GUID_NAME = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

_CURRENT_MEMBERSHIP = (
    "FILTER NOT HAS(e.meta, 'to_date') OR e.meta.to_date == null"
    " OR e.meta.to_date >= @today"
)


def get_committees(store: ArangoStore) -> list[dict[str, Any]]:
    """Every committee with the number of open dossiers it leads.

    ``active_dossier_count`` is precomputed on the node; the fallback derives
    it for the committees that lack it in one pass over the edges rather than
    one traversal per committee.
    """
    rows = list(
        store.query(
            f"""
        FOR committee IN {COLLECTION_COMMITTEES}
            LET name = committee.props.name
            FILTER name != null AND name != ""
            FILTER NOT REGEX_TEST(name, "{_GUID_NAME}", true)
            SORT name ASC
            RETURN MERGE(committee, {{
                active_dossier_count: committee.props.active_dossier_count
            }})
    """
        )
    )
    missing = [r["_id"] for r in rows if r.get("active_dossier_count") is None]
    if not missing:
        return rows

    counts = _open_dossier_counts(store, missing)
    for row in rows:
        if row.get("active_dossier_count") is None:
            row["active_dossier_count"] = counts.get(row["_id"], 0)
    return rows


def _open_dossier_counts(
    store: ArangoStore, committee_ids: list[str]
) -> dict[str, int]:
    """Open dossiers per committee, counted in one pass over two hash maps."""
    aql = f"""
    LET open_dossiers = MERGE(
        FOR dossier IN {COLLECTION_DOSSIERS}
            FILTER dossier.props.closed == false
            RETURN {{ [dossier._id]: true }}
    )
    LET open_activities = MERGE(
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @about
            FILTER open_dossiers[e._to] == true
            RETURN {{ [e._from]: true }}
    )
    LET counts = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @led_by
            FILTER e._to IN @committee_ids
            FILTER open_activities[e._from] == true
            COLLECT committee = e._to WITH COUNT INTO total
            RETURN {{ id: committee, count: total }}
    )
    RETURN MERGE(FOR row IN counts RETURN {{ [row.id]: row.count }})
    """
    bind = {
        "committee_ids": committee_ids,
        "about": RELATION_ABOUT,
        "led_by": RELATION_LED_BY,
    }
    counts: dict[str, int] = {}
    for row in store.query(aql, bind):
        if isinstance(row, dict):
            counts.update(row)
    return counts


def get_committees_with_members(store: ArangoStore) -> list[dict[str, Any]]:
    """Every committee with its current members inlined — one round trip.

    The parliamentary layer draws a halo of members around each committee;
    fetching them per committee would be 130 round trips.
    """
    aql = f"""
    LET today = DATE_FORMAT(DATE_NOW(), "%yyyy-%mm-%dd")
    LET committee_ids = (FOR c IN {COLLECTION_COMMITTEES} RETURN c._id)
    LET seats = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @member_of AND e._to IN committee_ids
            FILTER NOT HAS(e.meta, "to_date") OR e.meta.to_date == null
                OR e.meta.to_date >= today
            RETURN {{ member: e._from, committee: e._to }}
    )
    LET member_docs = MERGE(
        FOR id IN UNIQUE(seats[*].member)
            LET member = DOCUMENT(id)
            FILTER member != null
            RETURN {{ [member._id]: member }}
    )
    LET members_by_committee = MERGE(
        FOR seat IN seats
            COLLECT committee = seat.committee INTO group = seat.member
            RETURN {{ [committee]: (
                FOR id IN UNIQUE(group)
                    LET member = member_docs[id]
                    FILTER member != null
                    SORT member.props.name ASC
                    RETURN member
            ) }}
    )
    FOR committee IN {COLLECTION_COMMITTEES}
        LET name = committee.props.name
        FILTER name != null AND name != ""
        FILTER NOT REGEX_TEST(name, "{_GUID_NAME}", true)
        SORT name ASC
        RETURN MERGE(committee, {{
            members: members_by_committee[committee._id] != null
                ? members_by_committee[committee._id] : []
        }})
    """
    return list(store.query(aql, {"member_of": RELATION_MEMBER_OF}))


def get_committee_detail(
    store: ArangoStore,
    slug: str,
    *,
    current_only: bool = True,
    dossier_limit: int = 100,
) -> dict[str, Any] | None:
    """One committee with its members and the dossiers it leads.

    Accepts the committee's ``slug`` or its ``_key``. With *current_only* the
    members are those whose seat has no end date, or an end date still ahead.
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
                    to_date: e.meta.to_date
                }})
        )

        LET dossiers = (
            FOR led IN {COLLECTION_EDGES}
                FILTER led._to == committee._id AND led.relation == @led_by
                FOR subject IN {COLLECTION_EDGES}
                    FILTER subject._from == led._from
                        AND subject.relation == @about
                    FILTER STARTS_WITH(subject._to, "{COLLECTION_DOSSIERS}/")
                    LET dossier = DOCUMENT(subject._to)
                    FILTER dossier != null
                    RETURN DISTINCT dossier
            LIMIT @dossier_limit
        )

        RETURN MERGE(committee, {{ members: members, dossiers: dossiers }})
    """
    bind: dict[str, Any] = {
        "slug": slug.lower(),
        "dossier_limit": dossier_limit,
        "member_of": RELATION_MEMBER_OF,
        "led_by": RELATION_LED_BY,
        "about": RELATION_ABOUT,
    }
    if current_only:
        bind["today"] = dt.date.today().isoformat()
    for doc in store.query(aql, bind):
        return doc
    return None


def get_members(
    store: ArangoStore,
    *,
    party: str | None = None,
    active: bool | None = None,
    q: str | None = None,
    include_all: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Members of parliament, newest name order.

    Restricted to people who ever held a seat; *include_all* also returns the
    ministers and other people the TK Persoon endpoint exposes. *party*
    matches the current party or any abbreviation, name or alias in the
    member's faction timeline.
    """
    filters: list[str] = []
    bind: dict[str, Any] = {"limit": limit, "offset": offset, "active": active}

    if not include_all:
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
        filters.append("CONTAINS(LOWER(member.props.name), @q)")
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
        SORT member.props.name ASC
        LIMIT @offset, @limit
        RETURN member
    """
    return list(store.query(aql, bind))


def get_factions(
    store: ArangoStore,
    *,
    active: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """Every parliamentary party with its member count, seated ones first."""
    bind: dict[str, Any] = {"member_of": RELATION_MEMBER_OF}
    filters = ["faction.props.name != null AND faction.props.name != ''"]
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
                COLLECT instrument_id = part._to INTO documents = document_id
                LET document_count = LENGTH(UNIQUE(documents))
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
