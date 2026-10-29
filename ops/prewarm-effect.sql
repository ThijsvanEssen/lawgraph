-- What `lawgraph prewarm` left in memory after the nightly (B32), read only: whether pg_prewarm is installed, what
-- the buffers of PostgreSQL hold of the search of articles, dossiers and judgments (with pg_buffercache, when it
-- is installed), and how often their pages came from those buffers. The cold search itself: search-full-plan.sql
-- (its I/O Timings say whether a "shared read" came from disk or from the cache of the operating system).
SET default_transaction_read_only = on;
\pset pager off

-- 1. the extensions
SELECT name, installed_version FROM pg_available_extensions WHERE name IN ('pg_prewarm', 'pg_buffercache');

-- 2. what the buffers hold of each relation of the search (only with pg_buffercache)
SELECT EXISTS (SELECT FROM pg_extension WHERE extname = 'pg_buffercache') AS buffercache \gset
\if :buffercache
SELECT c.relname, pg_size_pretty(count(*) * 8192) AS in_buffers,
       round(100.0 * count(*) * 8192 / nullif(pg_relation_size(c.oid), 0), 1) AS pct
FROM pg_buffercache b JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid)
WHERE b.reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND (c.relname ~ '^(articles|dossiers|judgments)(_s_[a-z_]+_[tgpn])?$'
       OR c.oid IN (SELECT reltoastrelid FROM pg_class WHERE relname IN ('articles', 'dossiers', 'judgments')))
GROUP BY c.oid, c.relname ORDER BY count(*) DESC;
\else
\echo 'pg_buffercache is not installed: no view of the buffers'
\endif

-- 3. how often the pages of these tables came from the buffers since the statistics were reset
SELECT relname, heap_blks_read, heap_blks_hit, idx_blks_read, idx_blks_hit, toast_blks_read, toast_blks_hit,
       round(100.0 * heap_blks_hit / nullif(heap_blks_hit + heap_blks_read, 0), 1) AS heap_hit_pct,
       round(100.0 * idx_blks_hit / nullif(idx_blks_hit + idx_blks_read, 0), 1) AS idx_hit_pct
FROM pg_statio_user_tables WHERE relname IN ('articles', 'judgments', 'dossiers') ORDER BY relname;
SELECT stats_reset FROM pg_stat_database WHERE datname = current_database();
