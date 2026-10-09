-- Why judgments cite "Rv" as a law not in the graph (HR 2019:2006, Urgenda: "art. 419 Rv"), and
-- which laws are cited unresolved most. Read only; counts and a few rows. Run with:
--   docker exec -i lawgraph-postgres psql -X -U lawgraph -d lawgraph < unresolved-laws-check.sql > unresolved-laws-check-output.txt 2>&1
-- Sections 1-3 are cheap (instrument rows, one judgment). Section 4 reads `unresolved_citations`
-- from the props of a 0.5% sample of judgments (block sample, TOAST of those rows only): an
-- estimate of the top 20, not a full count.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. BWBR0001827 (Rv): in the graph, stub, short title and source abbreviations, articles'
SELECT i.key, i.stub, i.kind, i.article_count,
       i.props ->> 'short_title' AS short_title,
       i.props -> 'aliases' AS aliases,
       (SELECT count(*) FROM articles a WHERE a.bwb_id = 'BWBR0001827') AS articles_by_bwb_id
FROM instruments i
WHERE i.bwb_id = 'BWBR0001827';

\echo '== 2. Every instrument whose short title or source abbreviation is "Rv" (any case): a second claim makes it nobody''s'
SELECT i.key, i.bwb_id, i.celex, i.stub, i.props ->> 'short_title' AS short_title,
       i.props -> 'aliases' AS aliases
FROM instruments i
WHERE (i.bwb_id IS NOT NULL OR i.celex IS NOT NULL)
  AND (upper(i.props ->> 'short_title') = 'RV'
       OR EXISTS (SELECT 1 FROM json_array_elements_text(
                      CASE WHEN json_typeof(i.props -> 'aliases') = 'array'
                           THEN i.props -> 'aliases' ELSE '[]'::json END) a
                  WHERE upper(a) = 'RV'))
ORDER BY i.key;

\echo '== 3. ECLI:NL:HR:2019:2006: its unresolved laws, and its REFERS_TO edges into Rv articles'
SELECT j.key,
       (SELECT json_agg(DISTINCT u ->> 'law')
          FROM json_array_elements(
              CASE WHEN json_typeof(j.props -> 'unresolved_citations') = 'array'
                   THEN j.props -> 'unresolved_citations' ELSE '[]'::json END) u) AS unresolved_laws,
       (SELECT count(*) FROM edges e
          JOIN articles a ON a.id = e.to_id AND a.bwb_id = 'BWBR0001827'
         WHERE e.from_id = j.id AND e.relation = 'REFERS_TO') AS refers_to_rv
FROM judgments j
WHERE j.ecli = 'ECLI:NL:HR:2019:2006';

\echo '== 4. Top 20 unresolved laws in a 0.5% sample of judgments: judgments citing it, citations'
SELECT u ->> 'law' AS law,
       count(DISTINCT j.id) AS judgments_in_sample,
       sum(coalesce((u ->> 'mention_count')::int, 1)) AS mentions_in_sample
FROM judgments j TABLESAMPLE SYSTEM (0.5) REPEATABLE (1)
CROSS JOIN LATERAL json_array_elements(
    CASE WHEN json_typeof(j.props -> 'unresolved_citations') = 'array'
         THEN j.props -> 'unresolved_citations' ELSE '[]'::json END) u
GROUP BY 1
ORDER BY 2 DESC, 1
LIMIT 20;

\echo '== 5. Sample size (judgments read in section 4 and how many have any unresolved citation)'
SELECT count(*) AS judgments_in_sample,
       count(*) FILTER (WHERE json_typeof(j.props -> 'unresolved_citations') = 'array')
           AS with_unresolved
FROM judgments j TABLESAMPLE SYSTEM (0.5) REPEATABLE (1);
