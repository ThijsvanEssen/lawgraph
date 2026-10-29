-- What the search could keep in memory after the nightly (B32, pg_prewarm), read only: the memory of the host,
-- the caches of PostgreSQL, whether pg_prewarm is there, and the size of what the search of articles, judgments
-- and dossiers reads (its indexes, its heap and TOAST), beside the largest relations of the database.
SET default_transaction_read_only = on;
\pset pager off

-- 1. the caches and the libraries loaded at start
SELECT name, setting, unit, pg_size_pretty(pg_size_bytes(current_setting(name))) AS size
FROM pg_settings WHERE name IN ('shared_buffers', 'effective_cache_size', 'work_mem', 'maintenance_work_mem')
UNION ALL
SELECT name, setting, unit, NULL FROM pg_settings WHERE name IN ('shared_preload_libraries', 'max_connections', 'huge_pages');

-- 2. pg_prewarm (and pg_buffercache, to see what the buffers hold): available, installed
SELECT name, default_version, installed_version FROM pg_available_extensions WHERE name IN ('pg_prewarm', 'pg_buffercache');

-- 3. per table: heap, TOAST (with its index), the search indexes (s_*, search_words), the other indexes
WITH t AS (
  SELECT c.oid, c.relname, c.reltoastrelid FROM pg_class c
  WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
    AND c.relname IN ('articles', 'judgments', 'dossiers', 'instruments', 'documents', 'decisions')
), i AS (
  SELECT x.indrelid, pg_relation_size(x.indexrelid) AS bytes,
         ic.relname ~ '_(s_[a-z_]+_[tgpn]|search_words)$' AS search
  FROM pg_index x JOIN pg_class ic ON ic.oid = x.indexrelid
)
SELECT t.relname,
       pg_size_pretty(pg_relation_size(t.oid)) AS heap,
       pg_size_pretty(coalesce(pg_total_relation_size(nullif(t.reltoastrelid, 0)), 0)) AS toast,
       pg_size_pretty((SELECT coalesce(sum(bytes), 0) FROM i WHERE i.indrelid = t.oid AND search)) AS search_indexes,
       pg_size_pretty((SELECT coalesce(sum(bytes), 0) FROM i WHERE i.indrelid = t.oid AND NOT search)) AS other_indexes,
       pg_size_pretty(pg_total_relation_size(t.oid)) AS total
FROM t ORDER BY pg_total_relation_size(t.oid) DESC;

-- 4. each search index of articles, judgments and dossiers
SELECT x.indrelid::regclass AS "table", ic.relname AS index, pg_size_pretty(pg_relation_size(ic.oid)) AS size
FROM pg_index x JOIN pg_class ic ON ic.oid = x.indexrelid
WHERE x.indrelid::regclass::text IN ('articles', 'judgments', 'dossiers')
  AND ic.relname ~ '_(s_[a-z_]+_[tgpn]|search_words)$'
ORDER BY 1, pg_relation_size(ic.oid) DESC;

-- 5. the database, and its 15 largest relations (what the search would push out of the caches)
SELECT pg_size_pretty(pg_database_size(current_database())) AS database;
SELECT c.relname, c.relkind, coalesce(o.relname, '') AS toast_of, pg_size_pretty(pg_relation_size(c.oid)) AS size
FROM pg_class c LEFT JOIN pg_class o ON c.relkind = 't' AND o.reltoastrelid = c.oid WHERE c.relkind IN ('r', 'i', 't', 'm')
ORDER BY pg_relation_size(c.oid) DESC LIMIT 15;

-- 6. how often these tables were read from the caches of PostgreSQL since the statistics were reset
SELECT relname, heap_blks_read, heap_blks_hit, idx_blks_read, idx_blks_hit, toast_blks_read, toast_blks_hit,
       round(100.0 * heap_blks_hit / nullif(heap_blks_hit + heap_blks_read, 0), 1) AS heap_hit_pct,
       round(100.0 * idx_blks_hit / nullif(idx_blks_hit + idx_blks_read, 0), 1) AS idx_hit_pct
FROM pg_statio_user_tables WHERE relname IN ('articles', 'judgments', 'dossiers') ORDER BY relname;

-- 7. the memory of the host as the container sees it (kB), and the limit of the container's cgroup (last: pg_read_file needs a superuser)
SELECT m[1] AS name, pg_size_pretty(m[2]::bigint * 1024) AS size
FROM regexp_matches(pg_read_file('/proc/meminfo'), '^(MemTotal|MemAvailable|Cached|Buffers|SwapTotal|SwapFree):\s+(\d+) kB', 'gm') AS m;
