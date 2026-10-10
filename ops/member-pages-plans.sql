-- Why the page of a sitting member is slow cold: the plans with buffers of its votes
-- (get_member_votes, 1.26 s cold) and its dossiers (get_actor_dossiers, 2.79 s cold), for the
-- sitting member of the Tweede Kamer with the most faction periods. Read only (EXPLAIN ANALYZE
-- of two SELECTs: "read" blocks are those that came from disk).
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
SET track_io_timing = on;
\pset pager off

SELECT m.id AS member_id
FROM members m
WHERE EXISTS (
    SELECT 1 FROM json_array_elements(
        CASE WHEN json_typeof(m.props -> 'faction_memberships') = 'array'
             THEN m.props -> 'faction_memberships' ELSE '[]'::json END) f(p)
    WHERE coalesce(f.p ->> 'to_date', '') = '')
ORDER BY json_array_length(CASE WHEN json_typeof(m.props -> 'faction_memberships') = 'array'
             THEN m.props -> 'faction_memberships' ELSE '[]'::json END) DESC NULLS LAST,
         m.id ASC NULLS LAST
LIMIT 1 \gset
\echo '== member' :member_id

\echo '== votes'
EXPLAIN (ANALYZE, BUFFERS, TIMING, COSTS OFF)
WITH member AS (
        SELECT props FROM members WHERE id = :'member_id'
    ),
    periods AS (
        SELECT f.period, f.n
        FROM member
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(member.props -> 'faction_memberships') = 'array' THEN member.props -> 'faction_memberships' ELSE '[]'::json END
        ) WITH ORDINALITY AS f(period, n)
    ),
    -- per period the newest votes of the faction: the decisions of the period newest first
    -- (their index of the dates), each with the faction's vote on it; a faction votes on
    -- nearly every decision while it is seated, so few are read past the page (from the
    -- faction's side every vote it ever cast was read, a decision each: 441,000 for one
    -- member of seven periods)
    candidates AS (
        SELECT p.n, p.period, c.edge_key, c.decision_id, c.date, c.key
        FROM periods p
        CROSS JOIN LATERAL (
            SELECT v.key AS edge_key, d.id AS decision_id, d.date, d.key
            FROM decisions d
            CROSS JOIN LATERAL (SELECT p.period) AS f(period)
            -- per decision (never joined whole: that reads every vote of the faction)
            CROSS JOIN LATERAL (
                SELECT v.key FROM edges v
                WHERE v.to_id = d.id AND v.relation = 'VOTED'
                  AND v.from_collection = 'factions'
                  AND v.from_id = p.period ->> 'faction_id'
                OFFSET 0
            ) v
            -- the period's bounds as conditions of the index, so that the walk over the
            -- dates starts at the end of the period and stops at its start, not at the
            -- newest and the oldest decision (an old period passed 30,000 newer ones); the
            -- start as a row, as two plain bounds of one column are taken for a narrow
            -- range whose sort costs nothing, and the dates would be read whole and sorted;
            -- the test of the period itself stays
            WHERE ROW(d.date, d.key)
                  >= ROW(coalesce(lg_str(p.period -> 'from_date'), ''), '')
              AND d.date <= coalesce(lg_str(p.period -> 'to_date'), '9999-12-31')
              AND
    (coalesce(json_typeof(f.period -> 'from_date'), 'null') = 'null' OR lg_str(f.period -> 'from_date') <= d.date)
    AND (coalesce(json_typeof(f.period -> 'to_date'), 'null') = 'null' OR lg_str(f.period -> 'to_date') >= d.date)

            -- NULLS FIRST as the index of the dates walked backward gives it (no date is
            -- null here): the walk stops after the candidates instead of a sort of them all
            ORDER BY d.date DESC NULLS FIRST, d.key ASC
            LIMIT 200
        ) c
    ),
    -- of those, the votes no roll-call made
    kept AS (
        SELECT c.* FROM candidates c
        JOIN decisions d ON d.id = c.decision_id
        WHERE lg_str(d.props -> 'vote_kind') IS DISTINCT FROM 'member'
    ),
    voted AS (
        SELECT e.to_id AS decision_id, e.doc -> 'meta' AS meta,
               member.props -> 'party' AS party,
               NULL::json AS faction_key, NULL::text AS faction_order,
               'member'::text AS vote_source
        FROM member
        JOIN edges e
          ON e.from_id = :'member_id' AND e.relation = 'VOTED'
        UNION ALL
        SELECT k.decision_id, e.doc -> 'meta',
               CASE WHEN coalesce(json_typeof(k.period -> 'abbreviation'), 'null') = 'null'
                    THEN k.period -> 'name' ELSE k.period -> 'abbreviation' END,
               k.period -> 'faction_key', k.period ->> 'faction_key',
               'faction'::text
        FROM kept k JOIN edges e ON e.key = k.edge_key
    ),
    page AS (
        SELECT v.*, d.key, d.date
        FROM voted v JOIN decisions d ON d.id = v.decision_id
        ORDER BY d.date DESC NULLS LAST, d.key ASC, v.faction_order ASC NULLS FIRST
        LIMIT 100
    )
    SELECT
        -- a period cut at its candidates whose roll-calls left less than a page may lack
        -- votes of the page: read again with more
        NOT EXISTS (
            SELECT 1 FROM periods p
            WHERE (SELECT count(*) FROM candidates c WHERE c.n = p.n) = 200
              AND (SELECT count(*) FROM kept k WHERE k.n = p.n) < 100
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
                'vote_source', page.vote_source
            ) ORDER BY page.date DESC NULLS LAST, page.key ASC,
                       page.faction_order ASC NULLS FIRST)
            FROM page JOIN decisions d ON d.id = page.decision_id
        ), '[]'::json) AS votes;

\echo '== dossiers'
EXPLAIN (ANALYZE, BUFFERS, TIMING, COSTS OFF)
WITH authored AS (
    SELECT a.to_id AS document_id, a.doc -> 'meta' AS meta
    FROM edges a
    WHERE a.from_id = :'member_id' AND a.relation = 'AUTHORED'
),
        found AS (
            SELECT ids.dossier_id, a.document_id, a.meta
            FROM authored a
            CROSS JOIN LATERAL (
                SELECT p.to_id AS dossier_id
                FROM edges p
                WHERE p.from_id = a.document_id AND p.relation = 'PART_OF'
                  AND p.to_collection = 'dossiers'
                UNION
                SELECT p2.to_id
                FROM edges p1
                JOIN edges p2
                  ON p2.from_id = p1.to_id AND p2.relation = 'PART_OF'
                 AND p2.to_collection = 'dossiers'
                WHERE p1.from_id = a.document_id AND p1.relation = 'PART_OF'
                  AND p1.to_collection = 'cases'
            ) ids
        ),
        grouped AS (
            SELECT d.id, d.key, d.type, d.labels, d.props, d.opened_on,
                   coalesce(array_agg(DISTINCT r.meta ->> 'role' ORDER BY r.meta ->> 'role' ASC NULLS FIRST) FILTER (WHERE r.meta ->> 'role' <> ''), '{}') AS roles,
                   coalesce(array_agg(DISTINCT r.meta ->> 'function' ORDER BY r.meta ->> 'function' ASC NULLS FIRST) FILTER (WHERE r.meta ->> 'function' <> ''), '{}') AS functions,
                   coalesce(array_agg(DISTINCT r.meta ->> 'capacity' ORDER BY r.meta ->> 'capacity' ASC NULLS FIRST) FILTER (WHERE r.meta ->> 'capacity' IS NOT NULL), '{}') AS capacities,
                   count(DISTINCT r.document_id)::int AS document_count
            FROM found r JOIN dossiers d ON d.id = r.dossier_id
            GROUP BY d.id
        )

    SELECT counted.total, page.*
    FROM (SELECT count(*)::int AS total FROM grouped) counted
    LEFT JOIN LATERAL (
        SELECT * FROM grouped ORDER BY opened_on DESC NULLS LAST, key ASC
        LIMIT 100 OFFSET 0
    ) page ON true
    ORDER BY page.opened_on DESC NULLS LAST, page.key ASC;
