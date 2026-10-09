-- How often `semantic tk-amends` (source tk-amends-instrument) proposes the wrong targets: AMENDS
-- from a TK document to an EU instrument (it implements EU law, it cannot amend it), and AMENDS
-- from a document to the act its own dossier made (the instrument LEGISLATED_IN that dossier:
-- its citeertitel stands in the dossier title, "(Wet implementatie Europees centraal
-- toegangspunt)"). Read only; counts only; edges by relation and source (edges_relation index),
-- documents by their dossier_numbers column, instruments by columns; no props of a document.
-- Run with:
--   docker exec -i lawgraph-postgres psql -X -U lawgraph -d lawgraph < tk-amends-pattern-counts.sql > tk-amends-pattern-counts-output.txt 2>&1
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== AMENDS of tk-amends: all, to an EU instrument (celex), to a BWB instrument'
SELECT count(*) AS edges,
       count(*) FILTER (WHERE i.celex IS NOT NULL) AS to_eu,
       count(DISTINCT e.from_id) FILTER (WHERE i.celex IS NOT NULL) AS documents_to_eu,
       count(*) FILTER (WHERE i.bwb_id IS NOT NULL) AS to_bwb
FROM edges e
JOIN instruments i ON i.id = e.to_id
WHERE e.relation = 'AMENDS' AND e.source = 'tk-amends-instrument';

\echo '== AMENDS of tk-amends to the act the document''s own dossier made (LEGISLATED_IN that dossier)'
SELECT count(*) AS edges, count(DISTINCT e.from_id) AS documents,
       count(DISTINCT ds.id) AS dossiers
FROM edges e
JOIN documents d ON d.id = e.from_id
JOIN dossiers ds ON ds.label = ANY(d.dossier_numbers)
JOIN edges l ON l.from_id = e.to_id AND l.to_id = ds.id AND l.relation = 'LEGISLATED_IN'
WHERE e.relation = 'AMENDS' AND e.source = 'tk-amends-instrument';

\echo '== Five dossiers of that pattern, with the own act'
SELECT ds.label, i.key AS own_act, count(DISTINCT e.from_id) AS documents
FROM edges e
JOIN documents d ON d.id = e.from_id
JOIN dossiers ds ON ds.label = ANY(d.dossier_numbers)
JOIN edges l ON l.from_id = e.to_id AND l.to_id = ds.id AND l.relation = 'LEGISLATED_IN'
JOIN instruments i ON i.id = e.to_id
WHERE e.relation = 'AMENDS' AND e.source = 'tk-amends-instrument'
GROUP BY 1, 2
ORDER BY 3 DESC, 1
LIMIT 5;
