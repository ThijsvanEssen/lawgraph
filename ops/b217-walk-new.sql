-- B217: the walk of branch b217-neighborhood (lg_neighborhood, src/lawgraph/db/neighborhood_sql.py) on prod,
-- read only: as a DO block (it writes nothing; no function is made), timed, then the walk prod has on the same
-- node, timed, and whether both keep the same nodes. The new one runs first, so as cold as the database is.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== instruments/bwbr0005289, depth 3'
DO $$
DECLARE
    w_focal text := 'instruments/bwbr0005289';
    w_depth int := 3;
    w_cap int := 200;
    w_relations text[] := NULL;
    w_status text := NULL;
    w_outbound boolean := true;
    w_inbound boolean := true;
    w_collections text[] := NULL;
    w_tables text[] := '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}';
    w_stop text[] := NULL;
    w_seats text[] := '{"MEMBER_OF factions","SERVED_IN cabinets"}';
    t0 timestamptz := clock_timestamp();
    t1 timestamptz;
    old text[];
    seen text[];
    kept text[];
    frontier text[];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    reached text[];
    -- of the buckets of the frontier: the node, whether out of it, the relation, the other
    -- collection; how much of each is read, and whether that read holds enough
    b_node text[];
    b_outward boolean[];
    b_relation text[];
    b_other text[];
    reach int;
    whole boolean;
    -- what was reached, per read a run of it: its level, and what of it is not looked at yet
    queue text[];
    r_step int[];
    r_at int[];
    r_to int[];
    fair boolean;
    level text[];
    present text[];
    last int;
    room int;
    n int;
BEGIN
    <<walks>>
    -- one level has nothing to walk on from: its share is the whole cap
    FOREACH fair IN ARRAY ARRAY[w_depth = 1, true] LOOP
        seen := ARRAY[w_focal];
        kept := '{}';
        frontier := ARRAY[w_focal];
        queue := '{}';
        r_step := '{}';
        r_at := '{}';
        r_to := '{}';
        LOOP
            n := cardinality(kept);
            FOR step IN 1..w_depth LOOP
                free := ARRAY(SELECT x FROM unnest(frontier) x WHERE step = 1
                              OR split_part(x, '/', 1) <> ALL(coalesce(w_stop, '{}')));
                stopped := ARRAY(SELECT x FROM unnest(frontier) x
                                 WHERE step > 1 AND split_part(x, '/', 1) = ANY(w_stop));
                room := w_cap - cardinality(kept);
                -- the buckets of each node, one after the other in index order
                SELECT array_agg(b.node), array_agg(b.outward), array_agg(b.relation),
                       array_agg(b.other)
                INTO b_node, b_outward, b_relation, b_other
                FROM (
                    WITH RECURSIVE b(node, outward, relation, other) AS (
                        SELECT x, true, ''::text, ''::text FROM unnest(
                            CASE WHEN w_outbound THEN free END || stopped) x
                        UNION ALL
                        SELECT x, false, '', '' FROM unnest(CASE WHEN w_inbound THEN free END) x
                        UNION ALL
                        SELECT b.node, b.outward, s.relation, s.other FROM b CROSS JOIN LATERAL (
                            (SELECT e.relation, e.to_collection FROM public.edges e
                             WHERE b.outward AND e.from_id = b.node
                               AND (e.relation, e.to_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                            UNION ALL
                            (SELECT e.relation, e.from_collection FROM public.edges e
                             WHERE NOT b.outward AND e.to_id = b.node
                               AND (e.relation, e.from_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                        ) s(relation, other)
                    )
                    SELECT * FROM b
                    WHERE b.relation <> '' AND b.other = ANY(w_tables)
                      AND (w_collections IS NULL OR b.other = ANY(w_collections))
                      AND (w_relations IS NULL OR b.relation = ANY(w_relations))
                      AND (b.node <> ALL(stopped) OR b.relation || ' ' || b.other = ANY(w_seats))
                      AND (b.outward OR NOT public.lg_transposition_outcome(b.relation, b.node))
                ) b;
                reach := 2;
                LOOP
                    SELECT r.ids, r.whole INTO reached, whole FROM (
                        WITH k AS (
                            SELECT u.*, least(room + 1, ceil(reach * (room + 1.0) / count(*) OVER (
                                PARTITION BY u.outward, u.relation, u.other)))::int AS k
                            FROM unnest(b_node, b_outward, b_relation, b_other)
                                WITH ORDINALITY AS u(node, outward, relation, other, i)
                        ), got AS (
                            SELECT k.i, k.k, k.outward, k.relation, k.other, p.id, p.key
                            FROM k CROSS JOIN LATERAL (
                                (SELECT e.to_id AS id, e.key FROM public.edges e
                                 WHERE k.outward AND e.from_id = k.node AND e.relation = k.relation
                                   AND e.to_collection = k.other AND e.to_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.to_id
    )
                                 ORDER BY e.key LIMIT k.k)
                                UNION ALL
                                (SELECT e.from_id, e.key FROM public.edges e
                                 WHERE NOT k.outward AND e.to_id = k.node
                                   AND e.relation = k.relation AND e.from_collection = k.other
                                   AND e.from_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.from_id
    )
                                 ORDER BY e.key LIMIT k.k)
                            ) p
                        ), edge AS (
                            -- the key up to which each bucket of a share read short was read whole
                            SELECT c.outward, c.relation, c.other, min(c.top) AS top FROM (
                                SELECT g.outward, g.relation, g.other, max(g.key) AS top
                                FROM got g WHERE g.k <= room
                                GROUP BY g.i, g.k, g.outward, g.relation, g.other
                                HAVING count(*) = g.k
                            ) c GROUP BY 1, 2, 3
                        ), ranked AS (
                            SELECT t.*, row_number() OVER (
                                PARTITION BY t.outward, t.relation, t.other ORDER BY t.key) AS rank
                            FROM (
                                SELECT g.id, g.outward, g.relation, g.other, min(g.key) AS key,
                                       d.top IS NOT NULL AS cut
                                FROM got g LEFT JOIN edge d USING (outward, relation, other)
                                WHERE d.top IS NULL OR g.key <= d.top
                                GROUP BY 1, 2, 3, 4, 6
                            ) t
                        ), shares AS (
                            SELECT count(*) AS size, bool_or(ranked.cut) AS cut FROM ranked
                            GROUP BY outward, relation, other
                        ), upto AS (
                            SELECT least(room + 1, min(shares.size) FILTER (WHERE shares.cut)) AS t,
                                   NOT coalesce(bool_or(shares.cut), false) AS whole FROM shares
                        )
                        SELECT ARRAY(
                            SELECT x.id FROM ranked x WHERE x.rank <= u.t
                            ORDER BY x.rank, CASE WHEN x.outward THEN 'out ' ELSE 'in ' END
                                || x.relation NULLS LAST, x.other NULLS LAST, x.key
                        ) AS ids,
                        u.whole OR (SELECT sum(least(s.size, u.t)) FROM shares s) > room AS whole
                        FROM upto u
                    ) r;
                    EXIT WHEN whole;
                    reach := reach * 4;
                END LOOP;
                -- does not fit: walk again and share the cap out
                CONTINUE walks WHEN NOT fair
                    AND (SELECT count(DISTINCT x) FROM unnest(reached) x) > room;
                r_step := r_step || step;
                r_at := r_at || cardinality(queue) + 1;
                r_to := r_to || cardinality(queue) + cardinality(reached);
                queue := queue || reached;
                room := CASE WHEN fair AND step < w_depth THEN ceil(room / 2.0)::int ELSE room END;
                level := '{}';
                FOR i IN 1..cardinality(r_step) LOOP
                    CONTINUE WHEN r_step[i] <> step OR room = 0 OR r_at[i] > r_to[i];
                    -- the first of the run not seen yet, each once, as many as there is room for
                    SELECT coalesce(array_agg(t.id ORDER BY t.ord), '{}'), max(t.ord)
                    INTO present, last
                    FROM (
                        SELECT u.id, min(u.ord) AS ord
                        FROM unnest(queue[r_at[i]:r_to[i]]) WITH ORDINALITY AS u(id, ord)
                        LEFT JOIN unnest(seen) AS s(id) ON s.id = u.id
                        WHERE s.id IS NULL
                        GROUP BY u.id
                        ORDER BY 2
                        LIMIT room
                    ) t;
                    r_at[i] := CASE WHEN cardinality(present) < room THEN r_to[i] + 1
                                    ELSE r_at[i] + last END;
                    seen := seen || present;
                    level := level || present;
                    room := room - cardinality(present);
                END LOOP;
                kept := kept || level;
                frontier := level;
            END LOOP;
            frontier := '{}';
            -- a pass with room that keeps nothing has nothing left to keep
            IF cardinality(kept) IN (n, w_cap) OR NOT fair THEN
                BEGIN
                t1 := clock_timestamp();
                old := lg_neighborhood('instruments/bwbr0005289', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}');
                RAISE NOTICE 'instruments/bwbr0005289 depth 3: new % ms, % nodes; walk on prod % ms; the same: %',
                    round(extract(epoch FROM t1 - t0) * 1000), cardinality(kept),
                    round(extract(epoch FROM clock_timestamp() - t1) * 1000), kept = old;
                RETURN;
                END;
            END IF;
        END LOOP;
    END LOOP;
END
$$;

\echo '== instruments/bwbr0001840, depth 3'
DO $$
DECLARE
    w_focal text := 'instruments/bwbr0001840';
    w_depth int := 3;
    w_cap int := 200;
    w_relations text[] := NULL;
    w_status text := NULL;
    w_outbound boolean := true;
    w_inbound boolean := true;
    w_collections text[] := NULL;
    w_tables text[] := '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}';
    w_stop text[] := NULL;
    w_seats text[] := '{"MEMBER_OF factions","SERVED_IN cabinets"}';
    t0 timestamptz := clock_timestamp();
    t1 timestamptz;
    old text[];
    seen text[];
    kept text[];
    frontier text[];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    reached text[];
    -- of the buckets of the frontier: the node, whether out of it, the relation, the other
    -- collection; how much of each is read, and whether that read holds enough
    b_node text[];
    b_outward boolean[];
    b_relation text[];
    b_other text[];
    reach int;
    whole boolean;
    -- what was reached, per read a run of it: its level, and what of it is not looked at yet
    queue text[];
    r_step int[];
    r_at int[];
    r_to int[];
    fair boolean;
    level text[];
    present text[];
    last int;
    room int;
    n int;
BEGIN
    <<walks>>
    -- one level has nothing to walk on from: its share is the whole cap
    FOREACH fair IN ARRAY ARRAY[w_depth = 1, true] LOOP
        seen := ARRAY[w_focal];
        kept := '{}';
        frontier := ARRAY[w_focal];
        queue := '{}';
        r_step := '{}';
        r_at := '{}';
        r_to := '{}';
        LOOP
            n := cardinality(kept);
            FOR step IN 1..w_depth LOOP
                free := ARRAY(SELECT x FROM unnest(frontier) x WHERE step = 1
                              OR split_part(x, '/', 1) <> ALL(coalesce(w_stop, '{}')));
                stopped := ARRAY(SELECT x FROM unnest(frontier) x
                                 WHERE step > 1 AND split_part(x, '/', 1) = ANY(w_stop));
                room := w_cap - cardinality(kept);
                -- the buckets of each node, one after the other in index order
                SELECT array_agg(b.node), array_agg(b.outward), array_agg(b.relation),
                       array_agg(b.other)
                INTO b_node, b_outward, b_relation, b_other
                FROM (
                    WITH RECURSIVE b(node, outward, relation, other) AS (
                        SELECT x, true, ''::text, ''::text FROM unnest(
                            CASE WHEN w_outbound THEN free END || stopped) x
                        UNION ALL
                        SELECT x, false, '', '' FROM unnest(CASE WHEN w_inbound THEN free END) x
                        UNION ALL
                        SELECT b.node, b.outward, s.relation, s.other FROM b CROSS JOIN LATERAL (
                            (SELECT e.relation, e.to_collection FROM public.edges e
                             WHERE b.outward AND e.from_id = b.node
                               AND (e.relation, e.to_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                            UNION ALL
                            (SELECT e.relation, e.from_collection FROM public.edges e
                             WHERE NOT b.outward AND e.to_id = b.node
                               AND (e.relation, e.from_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                        ) s(relation, other)
                    )
                    SELECT * FROM b
                    WHERE b.relation <> '' AND b.other = ANY(w_tables)
                      AND (w_collections IS NULL OR b.other = ANY(w_collections))
                      AND (w_relations IS NULL OR b.relation = ANY(w_relations))
                      AND (b.node <> ALL(stopped) OR b.relation || ' ' || b.other = ANY(w_seats))
                      AND (b.outward OR NOT public.lg_transposition_outcome(b.relation, b.node))
                ) b;
                reach := 2;
                LOOP
                    SELECT r.ids, r.whole INTO reached, whole FROM (
                        WITH k AS (
                            SELECT u.*, least(room + 1, ceil(reach * (room + 1.0) / count(*) OVER (
                                PARTITION BY u.outward, u.relation, u.other)))::int AS k
                            FROM unnest(b_node, b_outward, b_relation, b_other)
                                WITH ORDINALITY AS u(node, outward, relation, other, i)
                        ), got AS (
                            SELECT k.i, k.k, k.outward, k.relation, k.other, p.id, p.key
                            FROM k CROSS JOIN LATERAL (
                                (SELECT e.to_id AS id, e.key FROM public.edges e
                                 WHERE k.outward AND e.from_id = k.node AND e.relation = k.relation
                                   AND e.to_collection = k.other AND e.to_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.to_id
    )
                                 ORDER BY e.key LIMIT k.k)
                                UNION ALL
                                (SELECT e.from_id, e.key FROM public.edges e
                                 WHERE NOT k.outward AND e.to_id = k.node
                                   AND e.relation = k.relation AND e.from_collection = k.other
                                   AND e.from_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.from_id
    )
                                 ORDER BY e.key LIMIT k.k)
                            ) p
                        ), edge AS (
                            -- the key up to which each bucket of a share read short was read whole
                            SELECT c.outward, c.relation, c.other, min(c.top) AS top FROM (
                                SELECT g.outward, g.relation, g.other, max(g.key) AS top
                                FROM got g WHERE g.k <= room
                                GROUP BY g.i, g.k, g.outward, g.relation, g.other
                                HAVING count(*) = g.k
                            ) c GROUP BY 1, 2, 3
                        ), ranked AS (
                            SELECT t.*, row_number() OVER (
                                PARTITION BY t.outward, t.relation, t.other ORDER BY t.key) AS rank
                            FROM (
                                SELECT g.id, g.outward, g.relation, g.other, min(g.key) AS key,
                                       d.top IS NOT NULL AS cut
                                FROM got g LEFT JOIN edge d USING (outward, relation, other)
                                WHERE d.top IS NULL OR g.key <= d.top
                                GROUP BY 1, 2, 3, 4, 6
                            ) t
                        ), shares AS (
                            SELECT count(*) AS size, bool_or(ranked.cut) AS cut FROM ranked
                            GROUP BY outward, relation, other
                        ), upto AS (
                            SELECT least(room + 1, min(shares.size) FILTER (WHERE shares.cut)) AS t,
                                   NOT coalesce(bool_or(shares.cut), false) AS whole FROM shares
                        )
                        SELECT ARRAY(
                            SELECT x.id FROM ranked x WHERE x.rank <= u.t
                            ORDER BY x.rank, CASE WHEN x.outward THEN 'out ' ELSE 'in ' END
                                || x.relation NULLS LAST, x.other NULLS LAST, x.key
                        ) AS ids,
                        u.whole OR (SELECT sum(least(s.size, u.t)) FROM shares s) > room AS whole
                        FROM upto u
                    ) r;
                    EXIT WHEN whole;
                    reach := reach * 4;
                END LOOP;
                -- does not fit: walk again and share the cap out
                CONTINUE walks WHEN NOT fair
                    AND (SELECT count(DISTINCT x) FROM unnest(reached) x) > room;
                r_step := r_step || step;
                r_at := r_at || cardinality(queue) + 1;
                r_to := r_to || cardinality(queue) + cardinality(reached);
                queue := queue || reached;
                room := CASE WHEN fair AND step < w_depth THEN ceil(room / 2.0)::int ELSE room END;
                level := '{}';
                FOR i IN 1..cardinality(r_step) LOOP
                    CONTINUE WHEN r_step[i] <> step OR room = 0 OR r_at[i] > r_to[i];
                    -- the first of the run not seen yet, each once, as many as there is room for
                    SELECT coalesce(array_agg(t.id ORDER BY t.ord), '{}'), max(t.ord)
                    INTO present, last
                    FROM (
                        SELECT u.id, min(u.ord) AS ord
                        FROM unnest(queue[r_at[i]:r_to[i]]) WITH ORDINALITY AS u(id, ord)
                        LEFT JOIN unnest(seen) AS s(id) ON s.id = u.id
                        WHERE s.id IS NULL
                        GROUP BY u.id
                        ORDER BY 2
                        LIMIT room
                    ) t;
                    r_at[i] := CASE WHEN cardinality(present) < room THEN r_to[i] + 1
                                    ELSE r_at[i] + last END;
                    seen := seen || present;
                    level := level || present;
                    room := room - cardinality(present);
                END LOOP;
                kept := kept || level;
                frontier := level;
            END LOOP;
            frontier := '{}';
            -- a pass with room that keeps nothing has nothing left to keep
            IF cardinality(kept) IN (n, w_cap) OR NOT fair THEN
                BEGIN
                t1 := clock_timestamp();
                old := lg_neighborhood('instruments/bwbr0001840', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}');
                RAISE NOTICE 'instruments/bwbr0001840 depth 3: new % ms, % nodes; walk on prod % ms; the same: %',
                    round(extract(epoch FROM t1 - t0) * 1000), cardinality(kept),
                    round(extract(epoch FROM clock_timestamp() - t1) * 1000), kept = old;
                RETURN;
                END;
            END IF;
        END LOOP;
    END LOOP;
END
$$;

\echo '== instruments/bwbr0011353, depth 3'
DO $$
DECLARE
    w_focal text := 'instruments/bwbr0011353';
    w_depth int := 3;
    w_cap int := 200;
    w_relations text[] := NULL;
    w_status text := NULL;
    w_outbound boolean := true;
    w_inbound boolean := true;
    w_collections text[] := NULL;
    w_tables text[] := '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}';
    w_stop text[] := NULL;
    w_seats text[] := '{"MEMBER_OF factions","SERVED_IN cabinets"}';
    t0 timestamptz := clock_timestamp();
    t1 timestamptz;
    old text[];
    seen text[];
    kept text[];
    frontier text[];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    reached text[];
    -- of the buckets of the frontier: the node, whether out of it, the relation, the other
    -- collection; how much of each is read, and whether that read holds enough
    b_node text[];
    b_outward boolean[];
    b_relation text[];
    b_other text[];
    reach int;
    whole boolean;
    -- what was reached, per read a run of it: its level, and what of it is not looked at yet
    queue text[];
    r_step int[];
    r_at int[];
    r_to int[];
    fair boolean;
    level text[];
    present text[];
    last int;
    room int;
    n int;
BEGIN
    <<walks>>
    -- one level has nothing to walk on from: its share is the whole cap
    FOREACH fair IN ARRAY ARRAY[w_depth = 1, true] LOOP
        seen := ARRAY[w_focal];
        kept := '{}';
        frontier := ARRAY[w_focal];
        queue := '{}';
        r_step := '{}';
        r_at := '{}';
        r_to := '{}';
        LOOP
            n := cardinality(kept);
            FOR step IN 1..w_depth LOOP
                free := ARRAY(SELECT x FROM unnest(frontier) x WHERE step = 1
                              OR split_part(x, '/', 1) <> ALL(coalesce(w_stop, '{}')));
                stopped := ARRAY(SELECT x FROM unnest(frontier) x
                                 WHERE step > 1 AND split_part(x, '/', 1) = ANY(w_stop));
                room := w_cap - cardinality(kept);
                -- the buckets of each node, one after the other in index order
                SELECT array_agg(b.node), array_agg(b.outward), array_agg(b.relation),
                       array_agg(b.other)
                INTO b_node, b_outward, b_relation, b_other
                FROM (
                    WITH RECURSIVE b(node, outward, relation, other) AS (
                        SELECT x, true, ''::text, ''::text FROM unnest(
                            CASE WHEN w_outbound THEN free END || stopped) x
                        UNION ALL
                        SELECT x, false, '', '' FROM unnest(CASE WHEN w_inbound THEN free END) x
                        UNION ALL
                        SELECT b.node, b.outward, s.relation, s.other FROM b CROSS JOIN LATERAL (
                            (SELECT e.relation, e.to_collection FROM public.edges e
                             WHERE b.outward AND e.from_id = b.node
                               AND (e.relation, e.to_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                            UNION ALL
                            (SELECT e.relation, e.from_collection FROM public.edges e
                             WHERE NOT b.outward AND e.to_id = b.node
                               AND (e.relation, e.from_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                        ) s(relation, other)
                    )
                    SELECT * FROM b
                    WHERE b.relation <> '' AND b.other = ANY(w_tables)
                      AND (w_collections IS NULL OR b.other = ANY(w_collections))
                      AND (w_relations IS NULL OR b.relation = ANY(w_relations))
                      AND (b.node <> ALL(stopped) OR b.relation || ' ' || b.other = ANY(w_seats))
                      AND (b.outward OR NOT public.lg_transposition_outcome(b.relation, b.node))
                ) b;
                reach := 2;
                LOOP
                    SELECT r.ids, r.whole INTO reached, whole FROM (
                        WITH k AS (
                            SELECT u.*, least(room + 1, ceil(reach * (room + 1.0) / count(*) OVER (
                                PARTITION BY u.outward, u.relation, u.other)))::int AS k
                            FROM unnest(b_node, b_outward, b_relation, b_other)
                                WITH ORDINALITY AS u(node, outward, relation, other, i)
                        ), got AS (
                            SELECT k.i, k.k, k.outward, k.relation, k.other, p.id, p.key
                            FROM k CROSS JOIN LATERAL (
                                (SELECT e.to_id AS id, e.key FROM public.edges e
                                 WHERE k.outward AND e.from_id = k.node AND e.relation = k.relation
                                   AND e.to_collection = k.other AND e.to_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.to_id
    )
                                 ORDER BY e.key LIMIT k.k)
                                UNION ALL
                                (SELECT e.from_id, e.key FROM public.edges e
                                 WHERE NOT k.outward AND e.to_id = k.node
                                   AND e.relation = k.relation AND e.from_collection = k.other
                                   AND e.from_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.from_id
    )
                                 ORDER BY e.key LIMIT k.k)
                            ) p
                        ), edge AS (
                            -- the key up to which each bucket of a share read short was read whole
                            SELECT c.outward, c.relation, c.other, min(c.top) AS top FROM (
                                SELECT g.outward, g.relation, g.other, max(g.key) AS top
                                FROM got g WHERE g.k <= room
                                GROUP BY g.i, g.k, g.outward, g.relation, g.other
                                HAVING count(*) = g.k
                            ) c GROUP BY 1, 2, 3
                        ), ranked AS (
                            SELECT t.*, row_number() OVER (
                                PARTITION BY t.outward, t.relation, t.other ORDER BY t.key) AS rank
                            FROM (
                                SELECT g.id, g.outward, g.relation, g.other, min(g.key) AS key,
                                       d.top IS NOT NULL AS cut
                                FROM got g LEFT JOIN edge d USING (outward, relation, other)
                                WHERE d.top IS NULL OR g.key <= d.top
                                GROUP BY 1, 2, 3, 4, 6
                            ) t
                        ), shares AS (
                            SELECT count(*) AS size, bool_or(ranked.cut) AS cut FROM ranked
                            GROUP BY outward, relation, other
                        ), upto AS (
                            SELECT least(room + 1, min(shares.size) FILTER (WHERE shares.cut)) AS t,
                                   NOT coalesce(bool_or(shares.cut), false) AS whole FROM shares
                        )
                        SELECT ARRAY(
                            SELECT x.id FROM ranked x WHERE x.rank <= u.t
                            ORDER BY x.rank, CASE WHEN x.outward THEN 'out ' ELSE 'in ' END
                                || x.relation NULLS LAST, x.other NULLS LAST, x.key
                        ) AS ids,
                        u.whole OR (SELECT sum(least(s.size, u.t)) FROM shares s) > room AS whole
                        FROM upto u
                    ) r;
                    EXIT WHEN whole;
                    reach := reach * 4;
                END LOOP;
                -- does not fit: walk again and share the cap out
                CONTINUE walks WHEN NOT fair
                    AND (SELECT count(DISTINCT x) FROM unnest(reached) x) > room;
                r_step := r_step || step;
                r_at := r_at || cardinality(queue) + 1;
                r_to := r_to || cardinality(queue) + cardinality(reached);
                queue := queue || reached;
                room := CASE WHEN fair AND step < w_depth THEN ceil(room / 2.0)::int ELSE room END;
                level := '{}';
                FOR i IN 1..cardinality(r_step) LOOP
                    CONTINUE WHEN r_step[i] <> step OR room = 0 OR r_at[i] > r_to[i];
                    -- the first of the run not seen yet, each once, as many as there is room for
                    SELECT coalesce(array_agg(t.id ORDER BY t.ord), '{}'), max(t.ord)
                    INTO present, last
                    FROM (
                        SELECT u.id, min(u.ord) AS ord
                        FROM unnest(queue[r_at[i]:r_to[i]]) WITH ORDINALITY AS u(id, ord)
                        LEFT JOIN unnest(seen) AS s(id) ON s.id = u.id
                        WHERE s.id IS NULL
                        GROUP BY u.id
                        ORDER BY 2
                        LIMIT room
                    ) t;
                    r_at[i] := CASE WHEN cardinality(present) < room THEN r_to[i] + 1
                                    ELSE r_at[i] + last END;
                    seen := seen || present;
                    level := level || present;
                    room := room - cardinality(present);
                END LOOP;
                kept := kept || level;
                frontier := level;
            END LOOP;
            frontier := '{}';
            -- a pass with room that keeps nothing has nothing left to keep
            IF cardinality(kept) IN (n, w_cap) OR NOT fair THEN
                BEGIN
                t1 := clock_timestamp();
                old := lg_neighborhood('instruments/bwbr0011353', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}');
                RAISE NOTICE 'instruments/bwbr0011353 depth 3: new % ms, % nodes; walk on prod % ms; the same: %',
                    round(extract(epoch FROM t1 - t0) * 1000), cardinality(kept),
                    round(extract(epoch FROM clock_timestamp() - t1) * 1000), kept = old;
                RETURN;
                END;
            END IF;
        END LOOP;
    END LOOP;
END
$$;

\echo '== instruments/bwbr0002629, depth 3'
DO $$
DECLARE
    w_focal text := 'instruments/bwbr0002629';
    w_depth int := 3;
    w_cap int := 200;
    w_relations text[] := NULL;
    w_status text := NULL;
    w_outbound boolean := true;
    w_inbound boolean := true;
    w_collections text[] := NULL;
    w_tables text[] := '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}';
    w_stop text[] := NULL;
    w_seats text[] := '{"MEMBER_OF factions","SERVED_IN cabinets"}';
    t0 timestamptz := clock_timestamp();
    t1 timestamptz;
    old text[];
    seen text[];
    kept text[];
    frontier text[];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    reached text[];
    -- of the buckets of the frontier: the node, whether out of it, the relation, the other
    -- collection; how much of each is read, and whether that read holds enough
    b_node text[];
    b_outward boolean[];
    b_relation text[];
    b_other text[];
    reach int;
    whole boolean;
    -- what was reached, per read a run of it: its level, and what of it is not looked at yet
    queue text[];
    r_step int[];
    r_at int[];
    r_to int[];
    fair boolean;
    level text[];
    present text[];
    last int;
    room int;
    n int;
BEGIN
    <<walks>>
    -- one level has nothing to walk on from: its share is the whole cap
    FOREACH fair IN ARRAY ARRAY[w_depth = 1, true] LOOP
        seen := ARRAY[w_focal];
        kept := '{}';
        frontier := ARRAY[w_focal];
        queue := '{}';
        r_step := '{}';
        r_at := '{}';
        r_to := '{}';
        LOOP
            n := cardinality(kept);
            FOR step IN 1..w_depth LOOP
                free := ARRAY(SELECT x FROM unnest(frontier) x WHERE step = 1
                              OR split_part(x, '/', 1) <> ALL(coalesce(w_stop, '{}')));
                stopped := ARRAY(SELECT x FROM unnest(frontier) x
                                 WHERE step > 1 AND split_part(x, '/', 1) = ANY(w_stop));
                room := w_cap - cardinality(kept);
                -- the buckets of each node, one after the other in index order
                SELECT array_agg(b.node), array_agg(b.outward), array_agg(b.relation),
                       array_agg(b.other)
                INTO b_node, b_outward, b_relation, b_other
                FROM (
                    WITH RECURSIVE b(node, outward, relation, other) AS (
                        SELECT x, true, ''::text, ''::text FROM unnest(
                            CASE WHEN w_outbound THEN free END || stopped) x
                        UNION ALL
                        SELECT x, false, '', '' FROM unnest(CASE WHEN w_inbound THEN free END) x
                        UNION ALL
                        SELECT b.node, b.outward, s.relation, s.other FROM b CROSS JOIN LATERAL (
                            (SELECT e.relation, e.to_collection FROM public.edges e
                             WHERE b.outward AND e.from_id = b.node
                               AND (e.relation, e.to_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                            UNION ALL
                            (SELECT e.relation, e.from_collection FROM public.edges e
                             WHERE NOT b.outward AND e.to_id = b.node
                               AND (e.relation, e.from_collection) > (b.relation, b.other)
                             ORDER BY 1, 2 LIMIT 1)
                        ) s(relation, other)
                    )
                    SELECT * FROM b
                    WHERE b.relation <> '' AND b.other = ANY(w_tables)
                      AND (w_collections IS NULL OR b.other = ANY(w_collections))
                      AND (w_relations IS NULL OR b.relation = ANY(w_relations))
                      AND (b.node <> ALL(stopped) OR b.relation || ' ' || b.other = ANY(w_seats))
                      AND (b.outward OR NOT public.lg_transposition_outcome(b.relation, b.node))
                ) b;
                reach := 2;
                LOOP
                    SELECT r.ids, r.whole INTO reached, whole FROM (
                        WITH k AS (
                            SELECT u.*, least(room + 1, ceil(reach * (room + 1.0) / count(*) OVER (
                                PARTITION BY u.outward, u.relation, u.other)))::int AS k
                            FROM unnest(b_node, b_outward, b_relation, b_other)
                                WITH ORDINALITY AS u(node, outward, relation, other, i)
                        ), got AS (
                            SELECT k.i, k.k, k.outward, k.relation, k.other, p.id, p.key
                            FROM k CROSS JOIN LATERAL (
                                (SELECT e.to_id AS id, e.key FROM public.edges e
                                 WHERE k.outward AND e.from_id = k.node AND e.relation = k.relation
                                   AND e.to_collection = k.other AND e.to_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.to_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.to_id
    )
                                 ORDER BY e.key LIMIT k.k)
                                UNION ALL
                                (SELECT e.from_id, e.key FROM public.edges e
                                 WHERE NOT k.outward AND e.to_id = k.node
                                   AND e.relation = k.relation AND e.from_collection = k.other
                                   AND e.from_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND EXISTS (
        SELECT 1 FROM public.instruments x WHERE k.other = 'instruments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.articles x WHERE k.other = 'articles' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.instrument_versions x WHERE k.other = 'instrument_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.article_versions x WHERE k.other = 'article_versions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cases x WHERE k.other = 'cases' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.documents x WHERE k.other = 'documents' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.judgments x WHERE k.other = 'judgments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.dossiers x WHERE k.other = 'dossiers' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.activities x WHERE k.other = 'activities' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.decisions x WHERE k.other = 'decisions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.commitments x WHERE k.other = 'commitments' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.committees x WHERE k.other = 'committees' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.members x WHERE k.other = 'members' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.factions x WHERE k.other = 'factions' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.cabinets x WHERE k.other = 'cabinets' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.ministries x WHERE k.other = 'ministries' AND x.id = e.from_id
        UNION ALL
        SELECT 1 FROM public.annexes x WHERE k.other = 'annexes' AND x.id = e.from_id
    )
                                 ORDER BY e.key LIMIT k.k)
                            ) p
                        ), edge AS (
                            -- the key up to which each bucket of a share read short was read whole
                            SELECT c.outward, c.relation, c.other, min(c.top) AS top FROM (
                                SELECT g.outward, g.relation, g.other, max(g.key) AS top
                                FROM got g WHERE g.k <= room
                                GROUP BY g.i, g.k, g.outward, g.relation, g.other
                                HAVING count(*) = g.k
                            ) c GROUP BY 1, 2, 3
                        ), ranked AS (
                            SELECT t.*, row_number() OVER (
                                PARTITION BY t.outward, t.relation, t.other ORDER BY t.key) AS rank
                            FROM (
                                SELECT g.id, g.outward, g.relation, g.other, min(g.key) AS key,
                                       d.top IS NOT NULL AS cut
                                FROM got g LEFT JOIN edge d USING (outward, relation, other)
                                WHERE d.top IS NULL OR g.key <= d.top
                                GROUP BY 1, 2, 3, 4, 6
                            ) t
                        ), shares AS (
                            SELECT count(*) AS size, bool_or(ranked.cut) AS cut FROM ranked
                            GROUP BY outward, relation, other
                        ), upto AS (
                            SELECT least(room + 1, min(shares.size) FILTER (WHERE shares.cut)) AS t,
                                   NOT coalesce(bool_or(shares.cut), false) AS whole FROM shares
                        )
                        SELECT ARRAY(
                            SELECT x.id FROM ranked x WHERE x.rank <= u.t
                            ORDER BY x.rank, CASE WHEN x.outward THEN 'out ' ELSE 'in ' END
                                || x.relation NULLS LAST, x.other NULLS LAST, x.key
                        ) AS ids,
                        u.whole OR (SELECT sum(least(s.size, u.t)) FROM shares s) > room AS whole
                        FROM upto u
                    ) r;
                    EXIT WHEN whole;
                    reach := reach * 4;
                END LOOP;
                -- does not fit: walk again and share the cap out
                CONTINUE walks WHEN NOT fair
                    AND (SELECT count(DISTINCT x) FROM unnest(reached) x) > room;
                r_step := r_step || step;
                r_at := r_at || cardinality(queue) + 1;
                r_to := r_to || cardinality(queue) + cardinality(reached);
                queue := queue || reached;
                room := CASE WHEN fair AND step < w_depth THEN ceil(room / 2.0)::int ELSE room END;
                level := '{}';
                FOR i IN 1..cardinality(r_step) LOOP
                    CONTINUE WHEN r_step[i] <> step OR room = 0 OR r_at[i] > r_to[i];
                    -- the first of the run not seen yet, each once, as many as there is room for
                    SELECT coalesce(array_agg(t.id ORDER BY t.ord), '{}'), max(t.ord)
                    INTO present, last
                    FROM (
                        SELECT u.id, min(u.ord) AS ord
                        FROM unnest(queue[r_at[i]:r_to[i]]) WITH ORDINALITY AS u(id, ord)
                        LEFT JOIN unnest(seen) AS s(id) ON s.id = u.id
                        WHERE s.id IS NULL
                        GROUP BY u.id
                        ORDER BY 2
                        LIMIT room
                    ) t;
                    r_at[i] := CASE WHEN cardinality(present) < room THEN r_to[i] + 1
                                    ELSE r_at[i] + last END;
                    seen := seen || present;
                    level := level || present;
                    room := room - cardinality(present);
                END LOOP;
                kept := kept || level;
                frontier := level;
            END LOOP;
            frontier := '{}';
            -- a pass with room that keeps nothing has nothing left to keep
            IF cardinality(kept) IN (n, w_cap) OR NOT fair THEN
                BEGIN
                t1 := clock_timestamp();
                old := lg_neighborhood('instruments/bwbr0002629', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}');
                RAISE NOTICE 'instruments/bwbr0002629 depth 3: new % ms, % nodes; walk on prod % ms; the same: %',
                    round(extract(epoch FROM t1 - t0) * 1000), cardinality(kept),
                    round(extract(epoch FROM clock_timestamp() - t1) * 1000), kept = old;
                RETURN;
                END;
            END IF;
        END LOOP;
    END LOOP;
END
$$;

\echo '== the statement of the route for the BW with the edges between the nodes read as on the branch (InitPlan 8)'
EXPLAIN (ANALYZE, BUFFERS)

                WITH walked AS (
                    SELECT lg_neighborhood(
                        'instruments/bwbr0005289', 3, 200, NULL, NULL,
                        true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}',
                        NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}') AS ids
                )
                SELECT
                    (SELECT coalesce(json_agg(json_build_array(
                         n.id, n.key, n.type, n.labels, (SELECT coalesce(json_object_agg(p.key,
            CASE WHEN p.key = 'actors' AND json_typeof(p.value) = 'array' THEN (SELECT coalesce(json_agg(json_build_object('role', a.actor -> 'role', 'name', a.actor -> 'name', 'faction', a.actor -> 'faction') ORDER BY a.n), '[]')
        FROM json_array_elements(p.value) WITH ORDINALITY AS a(actor, n))
                 ELSE p.value END
            ORDER BY p.n), '{}'::json)
        FROM (SELECT (CASE WHEN n.collection = 'judgments' THEN (SELECT l.props FROM lg_judgment_light l WHERE l.id = n.id) WHEN n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[]) THEN lg_update(lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']), json_strip_nulls(json_build_object('date', coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END)))) WHEN n.collection = 'activities' THEN lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb', 'case_ids', 'case_kinds_by_dossier']) WHEN n.collection = 'commitments' THEN lg_unset(n.props, ARRAY['paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) ELSE lg_unset(n.props, ARRAY['text', 'paragraphs', 'parties', 'subjects', 'judgment_metadata', 'raw_data', 'raw', 'entries', 'unresolved_citations', 'sections', 'footnotes', 'parts', 'tables', 'headings', 'footnote_marks', 'redactions', 'references', 'breadcrumb']) END) AS v) AS light
        CROSS JOIN LATERAL (
            SELECT * FROM json_each(
                CASE WHEN json_typeof(light.v) = 'object' THEN light.v END
            ) WITH ORDINALITY
            UNION ALL
            SELECT 'instrument_citation_title', to_json(coalesce(
                   nullif(i.citation_title, ''), nullif(t.title, ''))), 1000000::bigint
        FROM instruments i
        LEFT JOIN lg_instrument_names t ON t.id = i.id
        WHERE n.collection = 'instrument_versions'
          AND i.bwb_id = lg_str(n.props -> 'bwb_id')
          AND coalesce(nullif(i.citation_title, ''), nullif(t.title, '')) IS NOT NULL
        ) AS p(key, value, n)
        WHERE p.key = ANY((CASE n.collection WHEN 'articles' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'article_number', 'label', 'stam_id', 'instrument_citation_title', 'instrument_abbreviation', 'instrument_series_id', 'instrument_series_position', 'instrument_series_size', 'heading', 'caption', 'display_name']::text[] WHEN 'instruments' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'celex', 'title', 'citation_title', 'short_title', 'official_id', 'kind', 'jurisdiction', 'series_id', 'series_position', 'series_size', 'display_name']::text[] WHEN 'judgments' THEN ARRAY['stub', 'date', 'source', 'ecli', 'court', 'court_code', 'names', 'advocate_general', 'advocate_general_role', 'summary', 'translation_of', 'outcome', 'case_number', 'display_name']::text[] WHEN 'documents' THEN ARRAY['stub', 'date', 'source', 'kind', 'is_explanatory', 'number', 'sequence', 'title', 'subject', 'dossier_number', 'dossier_suffix', 'dossier_numbers', 'chamber', 'actors', 'outcome']::text[] WHEN 'dossiers' THEN ARRAY['stub', 'date', 'source', 'label', 'title', 'ek_name', 'name', 'number', 'suffix', 'subject']::text[] WHEN 'members' THEN ARRAY['stub', 'date', 'source', 'name', 'party', 'slug', 'full_name', 'display_name', 'government_functions', 'faction_memberships', 'ek']::text[] WHEN 'factions' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'chamber']::text[] WHEN 'committees' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'slug', 'title', 'chamber']::text[] WHEN 'cabinets' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'from_date', 'to_date']::text[] WHEN 'ministries' THEN ARRAY['stub', 'date', 'source', 'name', 'abbreviation', 'to_date']::text[] WHEN 'activities' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'dossier_numbers', 'number']::text[] WHEN 'commitments' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number']::text[] WHEN 'cases' THEN ARRAY['stub', 'date', 'source', 'kind', 'agenda_title', 'title', 'text', 'actors', 'number', 'citation_title']::text[] WHEN 'annexes' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'label', 'title', 'instrument_abbreviation', 'instrument_citation_title']::text[] WHEN 'instrument_versions' THEN ARRAY['stub', 'date', 'source', 'bwb_id', 'valid_from', 'valid_until', 'current', 'instrument_citation_title']::text[] WHEN 'decisions' THEN ARRAY['stub', 'date', 'source', 'subject', 'title', 'passed', 'chamber', 'kind', 'decision_kind', 'dossier_numbers', 'agenda_item_subject', 'result']::text[] ELSE ARRAY['stub', 'date', 'source']::text[] END)))) ORDER BY n.id), '[]')
                     FROM walked w, nodes n
                     WHERE n.id = ANY(w.ids) AND n.collection = ANY(ARRAY(SELECT DISTINCT split_part(x, '/', 1) FROM unnest(w.ids) x))
                    ) AS nodes,
                    (SELECT coalesce(json_agg(json_build_array(
                         e.key, e.from_id, e.to_id, e.doc) ORDER BY e.key), '[]')
                     FROM walked w, unnest(w.ids || 'instruments/bwbr0005289'::text) f(id), LATERAL (
                         SELECT c.key FROM edges c
                         WHERE c.from_id = f.id AND c.to_id = ANY(w.ids || 'instruments/bwbr0005289'::text)
                         ORDER BY c.relation NULLS LAST, c.to_collection NULLS LAST, c.key
                     ) c JOIN edges e ON e.key = c.key WHERE true ) AS edges,
                    (SELECT coalesce(lg_str(n.props -> 'date'), CASE WHEN n.collection = 'instruments' THEN CASE WHEN lg_str(n.props -> 'kind') = 'publicatie' THEN lg_str(n.props -> 'date_published') ELSE coalesce(lg_str(n.props -> 'version_date_in_force'), lg_str(n.props -> 'date_in_force')) END ELSE lg_str(n.props -> 'valid_from') END) FROM nodes n
                     WHERE n.id = 'instruments/bwbr0005289'
                       AND n.collection = ANY(ARRAY['instruments', 'instrument_versions', 'article_versions']::text[])) AS day
                FROM walked
                ;
