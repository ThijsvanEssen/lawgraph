-- How long the read of a build of the steps between sources takes on prod, read only (A285, semantic graph-steps,
-- src/lawgraph/db/queries/source_steps.py): the same pairs as the build, counted instead of written. The build adds
-- writing the rows (about 13 M) and two indexes on them; time it after the nightly.
SET default_transaction_read_only = on;
SET statement_timeout = '1800s';
SET work_mem = '256MB';
\pset pager off
\timing on

EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON)
WITH touch AS MATERIALIZED (
  SELECT DISTINCT t.x COLLATE "C" AS x, t.s COLLATE "C" AS s FROM (
    SELECT e.from_id AS x, e.to_id AS s FROM edges e
    WHERE e.to_collection IN ('instruments', 'articles') AND e.from_id <> e.to_id
      AND (e.relation IS DISTINCT FROM 'PART_OF' OR e.from_collection <> 'instruments' AND e.to_collection <> 'instruments')
    UNION ALL
    SELECT e.to_id, e.from_id FROM edges e
    WHERE e.from_collection IN ('instruments', 'articles') AND e.from_id <> e.to_id
      AND (e.relation IS DISTINCT FROM 'PART_OF' OR e.from_collection <> 'instruments' AND e.to_collection <> 'instruments')
  ) t
), nodes AS MATERIALIZED (
  SELECT x, count(*) AS sources FROM touch GROUP BY x HAVING count(*) >= 2
), through AS MATERIALIZED (
  SELECT t.x, t.s, 1 / ln(n.sources) AS weight FROM touch t JOIN nodes n USING (x) WHERE n.sources <= 50
)
SELECT count(*) FROM (
  SELECT c.a, c.b, sum(c.ways), bool_or(c.direct), sum(c.weight) FROM (
    SELECT p.s AS a, q.s AS b, 1 AS ways, false AS direct, p.weight
    FROM through p JOIN through q ON q.x = p.x AND p.s < q.s
    UNION ALL
    SELECT DISTINCT least(e.from_id COLLATE "C", e.to_id COLLATE "C"), greatest(e.from_id COLLATE "C", e.to_id COLLATE "C"),
           0, true, 1 / ln(2)
    FROM edges e
    WHERE e.from_collection IN ('instruments', 'articles') AND e.to_collection IN ('instruments', 'articles')
      AND e.from_id <> e.to_id
      AND (e.relation IS DISTINCT FROM 'PART_OF' OR e.from_collection <> 'instruments' AND e.to_collection <> 'instruments')
  ) c
  GROUP BY c.a, c.b
) steps;
