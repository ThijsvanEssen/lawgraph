-- The indexes of edges, read only: name, definition and size, and which index the page read of
-- lg_neighborhood (B209) takes for two hub articles. edges_to and edges_from (no key, not
-- covering) left the schema in 0.79.27; a database built before keeps them until dropped by hand,
-- and the planner may take one for a bucket, reading and sorting it whole.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off

\echo '== 1. the indexes of edges, with their size'
SELECT i.indexname, pg_size_pretty(pg_relation_size(format('%I.%I', i.schemaname, i.indexname)::regclass)) AS size,
       i.indexdef
FROM pg_indexes i
WHERE i.schemaname = current_schema() AND i.tablename = 'edges'
ORDER BY i.indexname;

\echo '== 2. the page read of a walk: 101 citing rulings of Awb 8:54 and EVRM art. 6, in key order'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT count(*)
FROM (VALUES ('articles/bwbr0005537_8_54'), ('articles/bwbv0001000_6')) AS b(node)
CROSS JOIN LATERAL (
    SELECT e.from_id, e.key FROM edges e
    WHERE e.to_id = b.node AND e.relation = 'REFERS_TO' AND e.from_collection = 'judgments'
      AND EXISTS (SELECT FROM judgments x WHERE x.id = e.from_id)
    ORDER BY e.key LIMIT 101
) p;
