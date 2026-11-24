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
# A level is not read whole. Its turns need of each share (a relation, direction and
# collection) its first nodes in key order, at most one more than the room left (w_cap less
# what is kept). Of each bucket of a node (a step through edges_from_cover or edges_to_cover)
# the walk reads the first edges to nodes there and not seen, in key order: first twice that
# room over the buckets of its share, four times as many each round after, one more than the
# room at most. Of a share read short, its nodes up to the lowest last key of a cut bucket are
# all it has up to there; the round is enough when those, as far as the turns go, make more
# than the room. So 60 articles cited by 300 papers each give 5 edges of each, not 141, and
# the walk keeps what a whole read would: a node of a cut bucket is passed over only when it
# is kept (before, or as itself), and no more than the room is kept after the read.
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
                                   AND {node_exists("e.to_id", "k.other")}
                                 ORDER BY e.key LIMIT k.k)
                                UNION ALL
                                (SELECT e.from_id, e.key FROM public.edges e
                                 WHERE NOT k.outward AND e.to_id = k.node
                                   AND e.relation = k.relation AND e.from_collection = k.other
                                   AND e.from_id <> ALL(seen)
                                   AND (w_status IS NULL OR e.status = w_status)
                                   AND {node_exists("e.from_id", "k.other")}
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
