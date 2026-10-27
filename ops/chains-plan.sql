-- Where level 2 of /api/chains spends its time, read only (A285): art. 6:162 BW -> 6:74 BW with max_steps=3 runs
-- into CHAINS_BUDGET (10 s, partial) on production, while the same SQL takes 0.3 s on a synthetic graph of the
-- same shape. The statement is lawgraph.db.queries.chains._NEIGHBORS_SQL with the values of that request (the
-- frontier: every neighbour of both ends; far: instruments and articles; share 8), under EXPLAIN (ANALYZE, BUFFERS),
-- then the size and visibility of edges (heap fetches of the index-only scans).
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
SET enable_bitmapscan = off;
\pset pager off
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
WITH fr AS (
  SELECT array_agg(DISTINCT n ORDER BY n) AS ids FROM (
    SELECT to_id AS n FROM edges WHERE from_id IN ('articles/bwbr0005289_162','articles/bwbr0005289_74')
    UNION ALL SELECT from_id FROM edges WHERE to_id IN ('articles/bwbr0005289_162','articles/bwbr0005289_74')
  ) x WHERE n NOT IN ('articles/bwbr0005289_162','articles/bwbr0005289_74'))
SELECT r.node, r.outbound, r.neighbor, r.key
FROM unnest((SELECT ids FROM fr)) AS f(id)
CROSS JOIN LATERAL (
    (SELECT e.from_id AS node, TRUE AS outbound, e.to_id AS neighbor, e.key
     FROM edges e WHERE e.from_id = f.id
       AND (e.relation <> 'PART_OF'
            OR NOT (e.from_collection = 'instruments' AND e.from_id <> ALL('{articles/bwbr0005289_162,articles/bwbr0005289_74}'::text[]))
               AND NOT (e.to_collection = 'instruments' AND e.to_id <> ALL('{articles/bwbr0005289_162,articles/bwbr0005289_74}'::text[])))
       AND e.to_collection = ANY('{instruments,articles}'::text[])
     ORDER BY e.relation NULLS LAST, e.to_collection NULLS LAST, e.key NULLS LAST
     LIMIT 8)
    UNION ALL
    (SELECT e.to_id, FALSE, e.from_id, e.key
     FROM edges e WHERE e.to_id = f.id
       AND (e.relation <> 'PART_OF'
            OR NOT (e.from_collection = 'instruments' AND e.from_id <> ALL('{articles/bwbr0005289_162,articles/bwbr0005289_74}'::text[]))
               AND NOT (e.to_collection = 'instruments' AND e.to_id <> ALL('{articles/bwbr0005289_162,articles/bwbr0005289_74}'::text[])))
       AND e.from_collection = ANY('{instruments,articles}'::text[])
     ORDER BY e.relation NULLS LAST, e.from_collection NULLS LAST, e.key NULLS LAST
     LIMIT 8)
) r
WHERE r.neighbor <> r.node
ORDER BY 3 NULLS LAST, 4 NULLS LAST
LIMIT 100000;
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_vacuum
FROM pg_stat_user_tables WHERE relname = 'edges';
SELECT relpages, relallvisible FROM pg_class WHERE relname = 'edges';
