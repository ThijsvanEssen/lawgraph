-- Is source_steps.via filled after the nightly build, and is the table still in cache? Read only (A299, docs/claude/onderzoek-ketens.md).
-- Rows, rows with a via, direct steps (which have none), the size of table and indexes, when the table was last
-- analyzed, and how much of each sits in shared_buffers (needs pg_buffercache; skipped when absent).
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== A. via filled'
SELECT count(*) AS steps, count(via) AS with_via, count(*) FILTER (WHERE direct) AS direct,
       count(*) FILTER (WHERE via IS NULL AND NOT direct) AS indirect_without_via
FROM source_steps;

\echo '== B. size and statistics'
SELECT c.relname, pg_size_pretty(pg_relation_size(c.oid)) AS size, c.reltuples::bigint AS est_rows,
       s.last_autoanalyze, s.last_analyze, s.n_live_tup
FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relname IN ('source_steps', 'source_step_nodes', 'source_steps_a', 'source_steps_b');

\echo '== C. share in shared_buffers'
SELECT c.relname, count(*) AS buffers, pg_size_pretty(count(*) * 8192) AS cached
FROM pg_buffercache b JOIN pg_class c ON c.relfilenode = b.relfilenode
WHERE c.relname IN ('source_steps', 'source_step_nodes', 'source_steps_a', 'source_steps_b')
GROUP BY c.relname ORDER BY 1;
