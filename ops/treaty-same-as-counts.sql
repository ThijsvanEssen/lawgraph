-- Before and after `semantic verdragenbank` with SAME_AS: BWB treaties by what their treaty number
-- finds (as `lawgraph check`), the SAME_AS edges of the step, and the BWB treaties and
-- Verdragenbank treaties without any edge. Read only; counts only; instrument columns (key,
-- kind, stub, treaty_number) and edges by `edges_from`/`edges_to`, no props. Run with:
--   docker exec -i lawgraph-postgres psql -X -U lawgraph -d lawgraph < treaty-same-as-counts.sql > treaty-same-as-counts-output.txt 2>&1
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== BWB treaties by match of their treaty number'
SELECT CASE
           WHEN t.treaty_number IS NULL THEN 'unnumbered'
           WHEN EXISTS (SELECT 1 FROM instruments r
                        WHERE r.treaty_number = t.treaty_number AND r.key LIKE 'verdrag\_%')
               THEN 'matched'
           ELSE 'unmatched'
       END AS match,
       count(*) AS treaties
FROM instruments t
WHERE t.kind = 'verdrag' AND t.key NOT LIKE 'verdrag\_%' AND t.stub IS NOT TRUE
GROUP BY 1
ORDER BY 1;

\echo '== SAME_AS edges from BWB treaties'
SELECT count(*) AS same_as_edges, count(DISTINCT e.to_id) AS verdragenbank_treaties
FROM instruments t
JOIN edges e ON e.from_id = t.id AND e.relation = 'SAME_AS'
WHERE t.kind = 'verdrag' AND t.key NOT LIKE 'verdrag\_%';

\echo '== Treaties without any edge: BWB text (kind verdrag), Verdragenbank record (key verdrag_)'
SELECT t.key LIKE 'verdrag\_%' AS verdragenbank,
       count(*) AS treaties,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = t.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = t.id))
           AS without_edges
FROM instruments t
WHERE t.stub IS NOT TRUE
  AND (t.key LIKE 'verdrag\_%' OR t.kind = 'verdrag')
GROUP BY 1
ORDER BY 1;
