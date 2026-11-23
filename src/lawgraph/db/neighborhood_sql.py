"""The walk of a neighbourhood in the database (``lg_neighborhood``), part of the schema
(``schema.statements``); ``queries.nodes.get_node_neighborhood`` calls it."""

from __future__ import annotations

from lawgraph.db.schema import node_exists

# The nodes within w_depth edges of w_focal, at most w_cap of them, in one statement. A walk
# that fits the cap is breadth first and keeps every node. One that does not shares the cap
# out in passes: going down the levels, each but the last takes at most half of the room left
# (so a hub does not fill the cap with its own neighbours), the last the rest; what is left
# over goes round again, and what a later pass keeps is walked on from too. A level (the
# neighbours along the edges asked for, not kept before) is kept in turns: the first of each
# relation, direction and collection, then the second of each (not every article of a law
# before any paper citing it), each in the key order of its edges (a hash: a spread, as a page
# of neighbours has it). A node that is gone is not one; one outside w_collections (when
# given) or w_tables is neither kept nor walked through. A node of w_stop (when given) but the
# focal one is kept but not walked through, but for its seats: an edge out of it whose
# relation and other collection are one of w_seats ('MEMBER_OF factions'). A law is not walked
# back to the old articles whose outcome it holds (lg_transposition_outcome).
# A level is not read whole: of each bucket of a node (a step through edges_from_cover or
# edges_to_cover) at most one more than the room left (w_cap less what is kept), in key order,
# of the nodes there and not seen; some 100 of a hub article's 30,000 citing rulings. That keeps
# what a whole read would: a node of a cut bucket is passed over only when it is kept (before,
# or as itself), and no more than that room is kept after the read.
NEIGHBORHOOD = f"""
CREATE OR REPLACE FUNCTION lg_neighborhood(
    w_focal text, w_depth int, w_cap int, w_relations text[], w_status text,
    w_outbound boolean, w_inbound boolean, w_collections text[], w_tables text[],
    w_stop text[], w_seats text[]
) RETURNS text[]
LANGUAGE plpgsql STABLE AS $$
DECLARE
    seen text[];
    kept text[];
    frontier text[];
    -- of the frontier: the nodes walked through, and those walked to their seats only
    free text[];
    stopped text[];
    reached text[];
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
        kept := '{{}}';
        frontier := ARRAY[w_focal];
        queue := '{{}}';
        r_step := '{{}}';
        r_at := '{{}}';
        r_to := '{{}}';
        LOOP
            n := cardinality(kept);
            FOR step IN 1..w_depth LOOP
                free := ARRAY(SELECT x FROM unnest(frontier) x WHERE step = 1
                              OR split_part(x, '/', 1) <> ALL(coalesce(w_stop, '{{}}')));
                stopped := ARRAY(SELECT x FROM unnest(frontier) x
                                 WHERE step > 1 AND split_part(x, '/', 1) = ANY(w_stop));
                room := w_cap - cardinality(kept);
                reached := ARRAY(
                    -- the buckets of each node, one after the other in index order
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
                    SELECT t.id FROM (
                        SELECT p.id, p.r, b.other, min(p.k) AS key, row_number() OVER (
                            PARTITION BY p.r, b.other ORDER BY min(p.k) NULLS LAST) AS rank
                        FROM b CROSS JOIN LATERAL (
                            (SELECT e.to_id AS id, 'out ' || e.relation AS r, e.key AS k
                             FROM public.edges e
                             WHERE b.outward AND e.from_id = b.node AND e.relation = b.relation
                               AND e.to_collection = b.other AND e.to_id <> ALL(seen)
                               AND (w_status IS NULL OR e.status = w_status)
                               AND {node_exists("e.to_id", "b.other")}
                             ORDER BY e.key LIMIT room + 1)
                            UNION ALL
                            (SELECT e.from_id, 'in ' || e.relation, e.key FROM public.edges e
                             WHERE NOT b.outward AND e.to_id = b.node AND e.relation = b.relation
                               AND e.from_collection = b.other AND e.from_id <> ALL(seen)
                               AND (w_status IS NULL OR e.status = w_status)
                               AND {node_exists("e.from_id", "b.other")}
                             ORDER BY e.key LIMIT room + 1)
                        ) p
                        WHERE b.relation <> '' AND b.other = ANY(w_tables)
                          AND (w_collections IS NULL OR b.other = ANY(w_collections))
                          AND (w_relations IS NULL OR b.relation = ANY(w_relations))
                          AND (b.node <> ALL(stopped)
                               OR b.relation || ' ' || b.other = ANY(w_seats))
                          AND (b.outward OR NOT public.lg_transposition_outcome(b.relation, b.node))
                        GROUP BY p.id, p.r, b.other
                    ) t
                    WHERE t.rank <= room + 1
                    ORDER BY t.rank, t.r NULLS LAST, t.other NULLS LAST, t.key
                );
                -- does not fit: walk again and share the cap out
                CONTINUE walks WHEN NOT fair
                    AND (SELECT count(DISTINCT x) FROM unnest(reached) x) > room;
                r_step := r_step || step;
                r_at := r_at || cardinality(queue) + 1;
                r_to := r_to || cardinality(queue) + cardinality(reached);
                queue := queue || reached;
                room := CASE WHEN fair AND step < w_depth THEN ceil(room / 2.0)::int ELSE room END;
                level := '{{}}';
                FOR i IN 1..cardinality(r_step) LOOP
                    CONTINUE WHEN r_step[i] <> step OR room = 0 OR r_at[i] > r_to[i];
                    -- the first of the run not seen yet, each once, as many as there is room for
                    SELECT coalesce(array_agg(t.id ORDER BY t.ord), '{{}}'), max(t.ord)
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
            frontier := '{{}}';
            -- a pass with room that keeps nothing has nothing left to keep
            IF cardinality(kept) IN (n, w_cap) OR NOT fair THEN
                RETURN kept;
            END IF;
        END LOOP;
    END LOOP;
END
$$;
"""
