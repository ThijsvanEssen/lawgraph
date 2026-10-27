-- Where the cold time of /api/chains goes (A298), read only: per pair, the statements the route runs in its
-- order, each under EXPLAIN (ANALYZE, BUFFERS) twice (as cold as the database is, then warm):
--   A. the steps of each end (source_steps, one range of each index);
--   B. the ways of the chains of two steps shown: every edge of the ends and of the 12 sources between, joined
--      (lawgraph.db.queries.chains._WAYS_SQL as of 0.80.13);
--   C. the chains of three steps: the steps between the 5,000 strongest sources of each end (_BETWEEN_SQL);
--   D. the ways of the chains of three steps shown (_WAYS_SQL, 12 chains).
-- The sources of B, C and D are chosen in SQL as the route chooses them, without its rule that a source between
-- the ends is in one chain shown only: the same sizes, not the same rows. Run it when the pairs have not been
-- asked for a while (else all of it is warm); 3 x 8 plans, a few minutes.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off
\timing on


\echo '######## 1. art. 6:162 BW -> 6:74 BW'

\set a 'articles/bwbr0005289_162'
\set b 'articles/bwbr0005289_74'

\echo '== 1A. the steps of articles/bwbr0005289_162, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);

\echo '== 1A. the steps of articles/bwbr0005289_162, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);


\echo '== 1A. the steps of articles/bwbr0005289_74, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_74']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_74']::text[]::text[]);

\echo '== 1A. the steps of articles/bwbr0005289_74, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_74']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_74']::text[]::text[]);


SELECT count(*) FILTER (WHERE l.node IS NOT NULL) AS steps_a,
       count(*) FILTER (WHERE r.node IS NOT NULL) AS steps_b,
       count(*) FILTER (WHERE l.node IS NOT NULL AND r.node IS NOT NULL) AS shared
FROM (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])) l
FULL JOIN (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])) r ON r.other = l.other;

WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
shared AS (SELECT l.other AS c, least(l.weight, r.weight) AS low, l.weight + r.weight AS sum
           FROM l JOIN r ON r.other = l.other WHERE l.other NOT IN (:'a', :'b')),
top AS (SELECT c FROM shared ORDER BY low DESC, sum DESC, c LIMIT 12)
SELECT array_agg(p.first ORDER BY p.n) AS firsts2, array_agg(p.second ORDER BY p.n) AS seconds2,
       (SELECT array_agg(c) FROM shared) AS used
FROM (SELECT :'a' AS first, :'b' AS second, 0 AS n
      UNION ALL SELECT :'a', c, 1 FROM top UNION ALL SELECT c, :'b', 2 FROM top) p
\gset

\echo '== 1B. the ways of the chains of two steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 1B. the ways of the chains of two steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[]))
SELECT (SELECT array_agg(other) FROM (SELECT other FROM l WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) x) AS near,
       (SELECT array_agg(other) FROM (SELECT other FROM r WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) y) AS far
\gset

\echo '== 1C. the steps between the sources of the ends, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);

\echo '== 1C. the steps between the sources of the ends, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
m AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[])),
three AS (SELECT m.node AS c, m.other AS d,
                 least(l.weight, m.weight, r.weight) AS low, l.weight + m.weight + r.weight AS sum
          FROM m JOIN l ON l.other = m.node JOIN r ON r.other = m.other WHERE m.node <> m.other),
top AS (SELECT c, d FROM three ORDER BY low DESC, sum DESC, c, d LIMIT 12)
SELECT (SELECT count(*) FROM three) AS chains3,
       array_agg(p.first ORDER BY p.n) AS firsts3, array_agg(p.second ORDER BY p.n) AS seconds3
FROM (SELECT :'a' AS first, c AS second, 1 AS n FROM top
      UNION ALL SELECT c, d, 2 FROM top UNION ALL SELECT d, :'b', 3 FROM top) p
\gset
\echo chains of three steps: :chains3

\echo '== 1D. the ways of the chains of three steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 1D. the ways of the chains of three steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0005289_162','articles/bwbr0005289_74']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


\echo '######## 2. art. 6 AVG -> 6:162 BW'

\set a 'articles/32016r0679_6'
\set b 'articles/bwbr0005289_162'

\echo '== 2A. the steps of articles/32016r0679_6, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/32016r0679_6']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/32016r0679_6']::text[]::text[]);

\echo '== 2A. the steps of articles/32016r0679_6, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/32016r0679_6']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/32016r0679_6']::text[]::text[]);


\echo '== 2A. the steps of articles/bwbr0005289_162, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);

\echo '== 2A. the steps of articles/bwbr0005289_162, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);


SELECT count(*) FILTER (WHERE l.node IS NOT NULL) AS steps_a,
       count(*) FILTER (WHERE r.node IS NOT NULL) AS steps_b,
       count(*) FILTER (WHERE l.node IS NOT NULL AND r.node IS NOT NULL) AS shared
FROM (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])) l
FULL JOIN (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])) r ON r.other = l.other;

WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
shared AS (SELECT l.other AS c, least(l.weight, r.weight) AS low, l.weight + r.weight AS sum
           FROM l JOIN r ON r.other = l.other WHERE l.other NOT IN (:'a', :'b')),
top AS (SELECT c FROM shared ORDER BY low DESC, sum DESC, c LIMIT 12)
SELECT array_agg(p.first ORDER BY p.n) AS firsts2, array_agg(p.second ORDER BY p.n) AS seconds2,
       (SELECT array_agg(c) FROM shared) AS used
FROM (SELECT :'a' AS first, :'b' AS second, 0 AS n
      UNION ALL SELECT :'a', c, 1 FROM top UNION ALL SELECT c, :'b', 2 FROM top) p
\gset

\echo '== 2B. the ways of the chains of two steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 2B. the ways of the chains of two steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[]))
SELECT (SELECT array_agg(other) FROM (SELECT other FROM l WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) x) AS near,
       (SELECT array_agg(other) FROM (SELECT other FROM r WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) y) AS far
\gset

\echo '== 2C. the steps between the sources of the ends, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);

\echo '== 2C. the steps between the sources of the ends, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
m AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[])),
three AS (SELECT m.node AS c, m.other AS d,
                 least(l.weight, m.weight, r.weight) AS low, l.weight + m.weight + r.weight AS sum
          FROM m JOIN l ON l.other = m.node JOIN r ON r.other = m.other WHERE m.node <> m.other),
top AS (SELECT c, d FROM three ORDER BY low DESC, sum DESC, c, d LIMIT 12)
SELECT (SELECT count(*) FROM three) AS chains3,
       array_agg(p.first ORDER BY p.n) AS firsts3, array_agg(p.second ORDER BY p.n) AS seconds3
FROM (SELECT :'a' AS first, c AS second, 1 AS n FROM top
      UNION ALL SELECT c, d, 2 FROM top UNION ALL SELECT d, :'b', 3 FROM top) p
\gset
\echo chains of three steps: :chains3

\echo '== 2D. the ways of the chains of three steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 2D. the ways of the chains of three steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/32016r0679_6','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


\echo '######## 3. art. 310 Sr -> 6:162 BW'

\set a 'articles/bwbr0001854_310'
\set b 'articles/bwbr0005289_162'

\echo '== 3A. the steps of articles/bwbr0001854_310, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0001854_310']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0001854_310']::text[]::text[]);

\echo '== 3A. the steps of articles/bwbr0001854_310, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0001854_310']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0001854_310']::text[]::text[]);


\echo '== 3A. the steps of articles/bwbr0005289_162, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);

\echo '== 3A. the steps of articles/bwbr0005289_162, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY['articles/bwbr0005289_162']::text[]::text[]);


SELECT count(*) FILTER (WHERE l.node IS NOT NULL) AS steps_a,
       count(*) FILTER (WHERE r.node IS NOT NULL) AS steps_b,
       count(*) FILTER (WHERE l.node IS NOT NULL AND r.node IS NOT NULL) AS shared
FROM (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])) l
FULL JOIN (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])) r ON r.other = l.other;

WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
shared AS (SELECT l.other AS c, least(l.weight, r.weight) AS low, l.weight + r.weight AS sum
           FROM l JOIN r ON r.other = l.other WHERE l.other NOT IN (:'a', :'b')),
top AS (SELECT c FROM shared ORDER BY low DESC, sum DESC, c LIMIT 12)
SELECT array_agg(p.first ORDER BY p.n) AS firsts2, array_agg(p.second ORDER BY p.n) AS seconds2,
       (SELECT array_agg(c) FROM shared) AS used
FROM (SELECT :'a' AS first, :'b' AS second, 0 AS n
      UNION ALL SELECT :'a', c, 1 FROM top UNION ALL SELECT c, :'b', 2 FROM top) p
\gset

\echo '== 3B. the ways of the chains of two steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 3B. the ways of the chains of two steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts2'::text[]::text[], :'seconds2'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[]))
SELECT (SELECT array_agg(other) FROM (SELECT other FROM l WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) x) AS near,
       (SELECT array_agg(other) FROM (SELECT other FROM r WHERE other <> ALL((coalesce(:'used'::text[], '{}') || ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
        ORDER BY weight DESC, other LIMIT 5000) y) AS far
\gset

\echo '== 3C. the steps between the sources of the ends, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);

\echo '== 3C. the steps between the sources of the ends, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[]);


WITH l AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'a']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'a']::text[]::text[])),
r AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(ARRAY[:'b']::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(ARRAY[:'b']::text[]::text[])),
m AS (SELECT s.a AS node, s.b AS other, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.a = ANY(:'near'::text[]::text[]) AND s.b = ANY(:'far'::text[]::text[])
UNION ALL
SELECT s.b, s.a, s.weight, s.ways, s.direct
FROM source_steps s WHERE s.b = ANY(:'near'::text[]::text[]) AND s.a = ANY(:'far'::text[]::text[])),
three AS (SELECT m.node AS c, m.other AS d,
                 least(l.weight, m.weight, r.weight) AS low, l.weight + m.weight + r.weight AS sum
          FROM m JOIN l ON l.other = m.node JOIN r ON r.other = m.other WHERE m.node <> m.other),
top AS (SELECT c, d FROM three ORDER BY low DESC, sum DESC, c, d LIMIT 12)
SELECT (SELECT count(*) FROM three) AS chains3,
       array_agg(p.first ORDER BY p.n) AS firsts3, array_agg(p.second ORDER BY p.n) AS seconds3
FROM (SELECT :'a' AS first, c AS second, 1 AS n FROM top
      UNION ALL SELECT c, d, 2 FROM top UNION ALL SELECT d, :'b', 3 FROM top) p
\gset
\echo chains of three steps: :chains3

\echo '== 3D. the ways of the chains of three steps, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;

\echo '== 3D. the ways of the chains of three steps, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH pair AS (
    SELECT p.first, p.second, p.i
    FROM unnest(:'firsts3'::text[]::text[], :'seconds3'::text[]::text[]) WITH ORDINALITY AS p(first, second, i)
), node AS (
    SELECT DISTINCT n.id
    FROM pair CROSS JOIN LATERAL unnest(ARRAY[pair.first, pair.second]) AS n(id)
), at AS MATERIALIZED (
    SELECT n.id, r.x, r.key, r.kept, r.followed FROM node n
    CROSS JOIN LATERAL (
        (SELECT e.to_id AS x, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments') AS kept, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))) AS followed
         FROM edges e WHERE e.from_id = n.id)
        UNION ALL
        (SELECT e.from_id, e.key, e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR e.from_collection <> 'instruments'
            AND e.to_collection <> 'instruments'), e.from_id <> e.to_id
    AND (e.relation IS DISTINCT FROM 'PART_OF'
         OR (e.from_collection <> 'instruments' OR e.from_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[]))
            AND (e.to_collection <> 'instruments' OR e.to_id = ANY(ARRAY['articles/bwbr0001854_310','articles/bwbr0005289_162']::text[])))
         FROM edges e WHERE e.to_id = n.id)
    ) r
)
SELECT p.i, f.x, min(f.key) AS from_first, min(s.key) AS to_second,
       coalesce(w.sources, 1) AS sources
FROM pair p
JOIN at f ON f.id = p.first AND f.kept
JOIN at s ON s.id = p.second AND s.x = f.x AND s.kept
LEFT JOIN source_step_nodes w ON w.id = f.x
GROUP BY p.i, f.x, w.sources
UNION ALL
SELECT p.i, NULL, min(f.key), NULL, 0
FROM pair p JOIN at f ON f.id = p.first AND f.x = p.second AND f.followed
GROUP BY p.i;


\echo '== the sizes'
SELECT c.relname, pg_size_pretty(pg_relation_size(c.oid)) AS size, c.relpages, c.relallvisible,
       pg_size_pretty(sum(pg_relation_size(c.oid)) OVER ()) AS together
FROM pg_class c WHERE c.relname IN ('source_steps', 'source_steps_a', 'source_steps_b', 'source_step_nodes',
  'source_step_nodes_pkey', 'edges', 'edges_to_cover', 'edges_from_cover', 'edges_pkey');
SELECT name, setting, unit FROM pg_settings WHERE name IN ('shared_buffers', 'effective_cache_size');
SELECT count(*) FILTER (WHERE name = 'pg_prewarm') AS prewarm_available FROM pg_available_extensions;
