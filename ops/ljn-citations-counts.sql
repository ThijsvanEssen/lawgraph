-- What the LJN citations add: the citations between judgments (REFERS_TO of judgment-citation-linker) from the
-- judgments of before 2014, when a decision was cited by its LJN, and how many judgments of CRvB 2011-2013 are loose.
-- Read only; run before and after `semantic rechtspraak-citations` over all. Reads the columns and the edges' indexes
-- only, no text.
--
-- 1. per year of the citing judgment (1999-2013): the citing judgments and their citations.
-- 2. CRvB 2011-2013: the judgments and those loose (no edge either way).
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. citations between judgments, per year of the citing one'
SELECT left(j.date_eff, 4) AS y, count(DISTINCT e.from_id) AS citing, count(*) AS citations
FROM edges e
JOIN judgments j ON j.id = e.from_id
WHERE e.relation = 'REFERS_TO' AND e.from_collection = 'judgments' AND e.to_collection = 'judgments'
  AND e.source = 'judgment-citation-linker' AND j.date_eff >= '1999' AND j.date_eff < '2014'
GROUP BY 1 ORDER BY 1;

\echo '== 2. CRvB 2011-2013: loose judgments'
SELECT left(j.date_eff, 4) AS y, count(*) AS judgments,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = j.id)) AS loose
FROM judgments j
WHERE j.source = 'rechtspraak' AND j.court_code = 'CRVB' AND j.date_eff >= '2011' AND j.date_eff < '2014'
GROUP BY 1 ORDER BY 1;
