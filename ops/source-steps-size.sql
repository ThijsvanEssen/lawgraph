-- How big a table of steps between sources (instruments, articles) would be, read only (A285, docs/claude/onderzoek-ketens.md).
-- A step joins two sources: by an edge between them, or by a node with an edge to both (any collection, PART_OF left
-- out). Per node x its sources k; x adds k(k-1)/2 pairs (an upper bound: two nodes can share the same pair). Then the
-- distinct ordered pairs of a 1 % sample of first sources (hashtext), times 100 = the rows of a table with both orders,
-- with no cap and with a cap of 200 and 50 sources per node, and those with at least 2 and 5 shared nodes.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
SET work_mem = '256MB';
\pset pager off

\echo '== A. nodes with sources, k per node, and the pairs they add (upper bound)'
WITH xs AS MATERIALIZED (
  SELECT DISTINCT x, s FROM (
    SELECT from_id AS x, to_id AS s FROM edges
    WHERE to_collection IN ('instruments', 'articles') AND relation <> 'PART_OF' AND from_id <> to_id
    UNION ALL
    SELECT to_id, from_id FROM edges
    WHERE from_collection IN ('instruments', 'articles') AND relation <> 'PART_OF' AND from_id <> to_id
  ) e
), k AS (SELECT x, count(*)::bigint AS k FROM xs GROUP BY x)
SELECT count(*) AS nodes,
       count(*) FILTER (WHERE k >= 2) AS nodes_k2,
       percentile_disc(ARRAY[0.5, 0.9, 0.99, 0.999]) WITHIN GROUP (ORDER BY k) AS k_p50_p90_p99_p999,
       max(k) AS k_max,
       count(*) FILTER (WHERE k > 200) AS nodes_over_200,
       count(*) FILTER (WHERE k > 50) AS nodes_over_50,
       sum(k * (k - 1) / 2) AS pairs_raw,
       sum(k * (k - 1) / 2) FILTER (WHERE k <= 200) AS pairs_raw_cap200,
       sum(k * (k - 1) / 2) FILTER (WHERE k <= 50) AS pairs_raw_cap50
FROM k;

\echo '== B. edges between two sources'
SELECT count(*) AS direct_edges
FROM edges
WHERE from_collection IN ('instruments', 'articles') AND to_collection IN ('instruments', 'articles')
  AND relation <> 'PART_OF' AND from_id <> to_id;

\echo '== C. distinct ordered pairs of a 1 % sample of first sources, times 100 = rows of the table'
WITH xs AS MATERIALIZED (
  SELECT DISTINCT x, s FROM (
    SELECT from_id AS x, to_id AS s FROM edges
    WHERE to_collection IN ('instruments', 'articles') AND relation <> 'PART_OF' AND from_id <> to_id
    UNION ALL
    SELECT to_id, from_id FROM edges
    WHERE from_collection IN ('instruments', 'articles') AND relation <> 'PART_OF' AND from_id <> to_id
  ) e
), k AS (SELECT x, count(*) AS k FROM xs GROUP BY x HAVING count(*) BETWEEN 2 AND 5000),
kx AS MATERIALIZED (SELECT xs.x, xs.s, k.k FROM xs JOIN k USING (x)),
pairs AS (
  SELECT a.s AS a, b.s AS b, count(*) AS shared, min(a.k) AS min_k, count(*) FILTER (WHERE a.k <= 200) AS shared200,
         count(*) FILTER (WHERE a.k <= 50) AS shared50
  FROM kx a JOIN kx b ON b.x = a.x AND b.s <> a.s
  WHERE abs(hashtext(a.s)) % 100 = 0
  GROUP BY a.s, b.s
)
SELECT 100 * count(*) AS rows_no_cap,
       100 * count(*) FILTER (WHERE shared200 > 0) AS rows_cap200,
       100 * count(*) FILTER (WHERE shared50 > 0) AS rows_cap50,
       100 * count(*) FILTER (WHERE shared200 >= 2) AS rows_cap200_shared2,
       100 * count(*) FILTER (WHERE shared200 >= 5) AS rows_cap200_shared5,
       percentile_disc(ARRAY[0.5, 0.9, 0.99]) WITHIN GROUP (ORDER BY shared200) AS ways_p50_p90_p99,
       count(DISTINCT a) AS sampled_sources
FROM pairs;
