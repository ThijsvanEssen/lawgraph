"""How a member voted: their roll-calls and the votes of their factions while they sat in
them (``/api/members/{key}/votes``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    RELATION_VOTED,
)
from lawgraph.core.tk_records.decisions import VOTE_KIND_MEMBER
from lawgraph.db import GraphStore
from lawgraph.db.queries._json_sql import array_or_empty, is_absent, period_holds
from lawgraph.db.queries._parliament_sql import IN_MEMBERSHIP
from lawgraph.db.queries.coalition_sql import coalition_factions, coalition_object

# The faction votes of a period read first, the newest by date, before which of them were
# roll-calls is known (``_member_votes_page``): a multiple of the page, as roll-calls are few.
VOTE_CANDIDATES = 2


def get_member_votes(
    store: GraphStore,
    member_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    in_office: bool | None = None,
) -> list[dict[str, Any]]:
    """How a member voted, newest first.

    Two kinds of vote reach a member. A roll-call names every member, so the
    VOTED edge starts at the member. Any other vote is cast by the faction,
    and counts for the member only while they belonged to it — which is what
    ``faction_memberships`` dates. ``party`` is the party they sat for at the
    time, so historic votes keep their colour after a switch.

    Whether a vote of the faction was a roll-call is in the props of its decision: of each
    period only the newest ``VOTE_CANDIDATES`` times the page are read for it (a large
    party votes tens of thousands of times), and more when the roll-calls among those
    leave less than a page.

    ``offset`` skips the newest that many; with *in_office* true only the votes cast while the
    member held a post of ``government_functions`` count, with false only those cast
    while they held none, before the page is cut.
    """
    candidates = max(limit + offset, 1) * VOTE_CANDIDATES
    while True:
        (row,) = store.query(
            _MEMBER_VOTES,
            _member_votes_params(member_id, limit, candidates, offset, in_office),
        )
        if row["complete"]:
            return list(row["votes"])
        candidates *= 4


def _member_votes_params(
    member_id: str,
    limit: int,
    candidates: int,
    offset: int = 0,
    in_office: bool | None = None,
) -> dict[str, Any]:
    return {
        "member_id": member_id,
        "limit": limit,
        "offset": offset,
        "page_end": limit + offset,
        "in_office": in_office,
        "candidates": candidates,
        "voted": RELATION_VOTED,
        "roll_call": VOTE_KIND_MEMBER,
    }


# With ``in_office`` true: a vote on a day the member held a post of ``government_functions``
# (both days included); false: a vote on a day they held none; null: every vote.
def _in_office_on(date: str) -> str:
    """SQL: whether *date* falls in a post of the member's ``government_functions`` as
    ``in_office`` asks (true, or false); true when it asks nothing (null)."""
    return f"""(%(in_office)s::boolean IS NULL OR %(in_office)s::boolean = EXISTS (
    SELECT 1 FROM {COLLECTION_MEMBERS} om
    CROSS JOIN LATERAL json_array_elements(
        {array_or_empty("om.props -> 'government_functions'")}
    ) AS g(post)
    WHERE om.id = %(member_id)s
      AND {period_holds("g.post -> 'from_date'", "g.post -> 'to_date'", date)}
))"""


# The candidates of the votes of a member's faction periods, read from ``lg_faction_votes``.
_CANDIDATES = f"""
    candidates AS (
        SELECT p.n, p.period, c.edge_key, c.decision_id, c.date, c.key, c.vote_kind
        FROM periods p
        CROSS JOIN LATERAL (
            -- the faction's votes of the period, newest first, from ``lg_faction_votes``:
            -- a range of its index, not a walk over the decisions with a probe of the
            -- edges per decision (5.7 s cold on prod for 9 periods)
            SELECT d.edge_key, d.decision_id, d.date, d.decision_key AS key, d.vote_kind
            FROM lg_faction_votes d
            CROSS JOIN LATERAL (SELECT p.period) AS f(period)
            WHERE d.faction_id = p.period ->> 'faction_id'
              AND ROW(d.date, d.decision_key)
                  >= ROW(p.first_day, '')
              AND d.date <= p.last_day
              AND {IN_MEMBERSHIP}
              AND {_in_office_on("d.date")}
            ORDER BY d.date DESC NULLS FIRST, d.decision_key ASC
            LIMIT %(candidates)s
        ) c
    ),
"""

# The posts of the member's ``government_functions`` held on the day ``d.date`` of a vote,
# oldest first: a Kamerlid who is also a (demissionary) bewindspersoon; read from the
# member's own props, no other table.
_IN_OFFICE = f"""(
    SELECT coalesce(json_agg(json_build_object(
               'function', g.post -> 'function',
               'cabinet_key', g.post -> 'cabinet_key',
               'cabinet', g.post -> 'cabinet'
           ) ORDER BY lg_str(g.post -> 'from_date') ASC NULLS FIRST, g.n ASC), '[]'::json)
    FROM member
    CROSS JOIN LATERAL json_array_elements(
        {array_or_empty("member.props -> 'government_functions'")}
    ) WITH ORDINALITY AS g(post, n)
    WHERE {period_holds("g.post -> 'from_date'", "g.post -> 'to_date'", "d.date")}
)"""


_MEMBER_VOTES = f"""
    WITH member AS (
        SELECT props FROM {COLLECTION_MEMBERS} WHERE id = %(member_id)s
    ),
    periods AS (
        SELECT f.period, f.n,
               greatest(s.first_day, o.first_day) AS first_day,
               least(s.last_day, o.last_day) AS last_day
        FROM member
        -- the periods in the factions of the Tweede Kamer and of the Eerste Kamer
        -- (``normalize eerstekamer-persons``), numbered as one list
        CROSS JOIN LATERAL json_array_elements((
            {array_or_empty("member.props -> 'faction_memberships'")}::jsonb
            || {array_or_empty("member.props -> 'ek_faction_memberships'")}::jsonb
        )::json) WITH ORDINALITY AS f(period, n)
        CROSS JOIN LATERAL (
            SELECT coalesce(lg_str(f.period -> 'from_date'), '') AS first_day,
                   coalesce(lg_str(f.period -> 'to_date'), '9999-12-31') AS last_day
        ) s
        -- with ``in_office`` the days of the period its votes are read in are those from
        -- the first to the last day of the posts that overlap it; a period no post
        -- overlaps is not read (its votes were walked and dropped one by one: 4 to 12 s
        -- on prod for every member page)
        CROSS JOIN LATERAL (
            SELECT min(coalesce(lg_str(g.post -> 'from_date'), '')) AS first_day,
                   max(coalesce(lg_str(g.post -> 'to_date'), '9999-12-31')) AS last_day
            FROM json_array_elements(
                {array_or_empty("member.props -> 'government_functions'")}
            ) AS g(post)
            WHERE %(in_office)s::boolean IS TRUE
              AND coalesce(lg_str(g.post -> 'from_date'), '') <= s.last_day
              AND coalesce(lg_str(g.post -> 'to_date'), '9999-12-31') >= s.first_day
        ) o
        WHERE %(in_office)s::boolean IS NOT TRUE OR o.first_day IS NOT NULL
    ),
    -- per period the newest votes of the faction: the decisions of the period newest first
    -- (their index of the dates), each with the faction's vote on it; a faction votes on
    -- nearly every decision while it is seated, so few are read past the page (from the
    -- faction's side every vote it ever cast was read, a decision each: 441,000 for one
    -- member of seven periods)
{_CANDIDATES}    -- of those, the votes no roll-call made
    kept AS (
        SELECT c.* FROM candidates c
        WHERE c.vote_kind IS DISTINCT FROM %(roll_call)s
    ),
    -- the votes without their edges' meta: the page is chosen first, and only the edges of
    -- its votes are read (each of a faction's candidates read its edge: 1,800 for 100)
    voted AS (
        -- an own vote (a roll-call) under the faction the member sat in that day, as a
        -- faction's vote: its party then, not the one of now (a roll-call of Mona
        -- Keijzer's CDA years is the CDA's, not "Lid Keijzer"); the party of now only
        -- where no period holds the day (an undated decision)
        SELECT e.to_id AS decision_id, e.key AS edge_key, d.key, d.date,
               CASE WHEN day.period IS NULL THEN member.props -> 'party'
                    WHEN {is_absent("day.period -> 'abbreviation'")}
                    THEN day.period -> 'name' ELSE day.period -> 'abbreviation'
               END AS party,
               day.period -> 'faction_key' AS faction_key, NULL::text AS faction_order,
               'member'::text AS vote_source
        FROM member
        JOIN {COLLECTION_EDGES} e
          ON e.from_id = %(member_id)s AND e.relation = %(voted)s
        JOIN {COLLECTION_DECISIONS} d ON d.id = e.to_id
        LEFT JOIN LATERAL (
            SELECT f.period
            FROM periods p
            CROSS JOIN LATERAL (SELECT p.period) AS f(period)
            WHERE d.date IS NOT NULL AND {IN_MEMBERSHIP}
            ORDER BY p.n DESC
            LIMIT 1
        ) day ON true
        WHERE {_in_office_on("d.date")}
        UNION ALL
        SELECT k.decision_id, k.edge_key, k.key, k.date,
               CASE WHEN {is_absent("k.period -> 'abbreviation'")}
                    THEN k.period -> 'name' ELSE k.period -> 'abbreviation' END,
               k.period -> 'faction_key', k.period ->> 'faction_key',
               'faction'::text
        FROM kept k
    ),
    chosen AS (
        SELECT * FROM voted
        ORDER BY date DESC NULLS LAST, key ASC, faction_order ASC NULLS FIRST
        LIMIT %(limit)s OFFSET %(offset)s
    ),
    page AS (
        SELECT c.*, e.doc -> 'meta' AS meta
        FROM chosen c JOIN {COLLECTION_EDGES} e ON e.key = c.edge_key
    )
    SELECT
        -- a period cut at its candidates whose roll-calls left less than a page may lack
        -- votes of the page: read again with more
        NOT EXISTS (
            SELECT 1 FROM periods p
            WHERE (SELECT count(*) FROM candidates c WHERE c.n = p.n) = %(candidates)s
              AND (SELECT count(*) FROM kept k WHERE k.n = p.n) < %(page_end)s
        ) AS complete,
        coalesce((
            SELECT json_agg(json_build_object(
                'decision_id', d.id,
                'decision_key', d.key,
                'external_id', d.props -> 'decision_id',
                'date', d.props -> 'date',
                'subject', d.props -> 'subject',
                'passed', d.props -> 'passed',
                'choice', page.meta -> 'choice',
                'seats', page.meta -> 'seats',
                'party', page.party,
                'faction_key', page.faction_key,
                'vote_source', page.vote_source,
                'in_office', {_IN_OFFICE},
                'coalition', {coalition_object("co")},
                'coalition_factions', {coalition_factions("co")}
            ) ORDER BY page.date DESC NULLS LAST, page.key ASC,
                       page.faction_order ASC NULLS FIRST)
            FROM page JOIN {COLLECTION_DECISIONS} d ON d.id = page.decision_id
            -- what the coalition did on it (``tk-coalition-votes``)
            LEFT JOIN lg_decision_coalition co ON co.id = page.decision_id
        ), '[]'::json) AS votes
"""
