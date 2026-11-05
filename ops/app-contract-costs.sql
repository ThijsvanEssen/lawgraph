-- What two proposed counts of the API would cost, read only (docs/claude/HANDOFF-app-contract.md, voorstel 4).
-- Each statement under EXPLAIN (ANALYZE, BUFFERS), twice: as cold as the database is, then warm.
-- A. judgment_total and echr_judgment_total of art. 6 EVRM counted live from lg_cited_by, beside the kept answer of
--    /cited-by, with the count /api/articles/... reads today as its measure.
-- B. buckets[].years and undated of the neighbourhood: the first level of a node, each neighbour with a date by the
--    date column of its table: of the WVW (a law with many papers) and of art. 6:162 BW (an article with many judgments).
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== A0. the rows of lg_cited_by of art. 6 EVRM'
SELECT count(*) FROM lg_cited_by c WHERE c.article_id = 'articles/bwbv0001000_6';

\echo '== A1. the two counts live, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(DISTINCT c.edge_key) FILTER (WHERE c.mentions > 0 OR c.court_code IS DISTINCT FROM 'ECHR')::int AS judgment_total,
       count(DISTINCT c.judgment_id) FILTER (WHERE c.court_code = 'ECHR')::int AS echr_judgment_total
FROM lg_cited_by c WHERE c.article_id = 'articles/bwbv0001000_6';

\echo '== A2. the two counts live, warm'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(DISTINCT c.edge_key) FILTER (WHERE c.mentions > 0 OR c.court_code IS DISTINCT FROM 'ECHR')::int AS judgment_total,
       count(DISTINCT c.judgment_id) FILTER (WHERE c.court_code = 'ECHR')::int AS echr_judgment_total
FROM lg_cited_by c WHERE c.article_id = 'articles/bwbv0001000_6';

\echo '== A3. the count of the article detail today (metadata.judgment_count), for comparison'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)::int FROM edges e
WHERE e.to_id = 'articles/bwbv0001000_6' AND e.relation = 'REFERS_TO' AND e.from_collection = 'judgments';

\echo '== B1. WVW per collection and year, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH x AS MATERIALIZED (
    SELECT e.to_id AS id FROM edges e WHERE e.from_id = 'instruments/bwbr0006622'
    UNION
    SELECT e.from_id FROM edges e WHERE e.to_id = 'instruments/bwbr0006622'
), dated AS (
    SELECT 'documents' AS collection, substr(t.date, 1, 4) AS year FROM x JOIN documents t ON t.id = x.id
    UNION ALL
    SELECT 'activities', substr(t.date, 1, 4) FROM x JOIN activities t ON t.id = x.id
    UNION ALL
    SELECT 'decisions', substr(t.date, 1, 4) FROM x JOIN decisions t ON t.id = x.id
    UNION ALL
    SELECT 'judgments', substr(t.date_eff, 1, 4) FROM x JOIN judgments t ON t.id = x.id
)
SELECT collection, year, count(*) FROM dated GROUP BY 1, 2;

\echo '== B2. WVW per collection and year, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH x AS MATERIALIZED (
    SELECT e.to_id AS id FROM edges e WHERE e.from_id = 'instruments/bwbr0006622'
    UNION
    SELECT e.from_id FROM edges e WHERE e.to_id = 'instruments/bwbr0006622'
), dated AS (
    SELECT 'documents' AS collection, substr(t.date, 1, 4) AS year FROM x JOIN documents t ON t.id = x.id
    UNION ALL
    SELECT 'activities', substr(t.date, 1, 4) FROM x JOIN activities t ON t.id = x.id
    UNION ALL
    SELECT 'decisions', substr(t.date, 1, 4) FROM x JOIN decisions t ON t.id = x.id
    UNION ALL
    SELECT 'judgments', substr(t.date_eff, 1, 4) FROM x JOIN judgments t ON t.id = x.id
)
SELECT collection, year, count(*) FROM dated GROUP BY 1, 2;

\echo '== B3. art. 6:162 BW per collection and year, as cold as it is'
EXPLAIN (ANALYZE, BUFFERS)
WITH x AS MATERIALIZED (
    SELECT e.to_id AS id FROM edges e WHERE e.from_id = 'articles/bwbr0005289_162'
    UNION
    SELECT e.from_id FROM edges e WHERE e.to_id = 'articles/bwbr0005289_162'
), dated AS (
    SELECT 'documents' AS collection, substr(t.date, 1, 4) AS year FROM x JOIN documents t ON t.id = x.id
    UNION ALL
    SELECT 'activities', substr(t.date, 1, 4) FROM x JOIN activities t ON t.id = x.id
    UNION ALL
    SELECT 'decisions', substr(t.date, 1, 4) FROM x JOIN decisions t ON t.id = x.id
    UNION ALL
    SELECT 'judgments', substr(t.date_eff, 1, 4) FROM x JOIN judgments t ON t.id = x.id
)
SELECT collection, year, count(*) FROM dated GROUP BY 1, 2;

\echo '== B4. art. 6:162 BW per collection and year, warm'
EXPLAIN (ANALYZE, BUFFERS)
WITH x AS MATERIALIZED (
    SELECT e.to_id AS id FROM edges e WHERE e.from_id = 'articles/bwbr0005289_162'
    UNION
    SELECT e.from_id FROM edges e WHERE e.to_id = 'articles/bwbr0005289_162'
), dated AS (
    SELECT 'documents' AS collection, substr(t.date, 1, 4) AS year FROM x JOIN documents t ON t.id = x.id
    UNION ALL
    SELECT 'activities', substr(t.date, 1, 4) FROM x JOIN activities t ON t.id = x.id
    UNION ALL
    SELECT 'decisions', substr(t.date, 1, 4) FROM x JOIN decisions t ON t.id = x.id
    UNION ALL
    SELECT 'judgments', substr(t.date_eff, 1, 4) FROM x JOIN judgments t ON t.id = x.id
)
SELECT collection, year, count(*) FROM dated GROUP BY 1, 2;
