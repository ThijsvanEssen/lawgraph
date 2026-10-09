-- Before and after the backfill of every SRU dossier number of an Eerste Kamer paper (`retrieve
-- eerstekamer --mode full`, `normalize eerstekamer`, `semantic eerstekamer`): EK papers by how many
-- dossiers they name, the PART_OF edges of the step into dossiers, and the EK papers without any
-- edge. Read only; counts only; document columns (source, dossier_numbers), edges by
-- `edges_from`, no props. Run with:
--   docker exec -i lawgraph-postgres psql -X -U lawgraph -d lawgraph < ek-all-dossiers-counts.sql > ek-all-dossiers-counts-output.txt 2>&1
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== EK papers by the number of dossiers they name'
SELECT coalesce(cardinality(d.dossier_numbers), 0) AS dossiers, count(*) AS papers
FROM documents d
WHERE d.source = 'eerstekamer'
GROUP BY 1
ORDER BY 1;

\echo '== PART_OF from EK papers into dossiers (ek-dossier-linker): edges, papers'
SELECT count(*) AS edges, count(DISTINCT e.from_id) AS papers
FROM documents d
JOIN edges e ON e.from_id = d.id AND e.relation = 'PART_OF' AND e.to_collection = 'dossiers'
WHERE d.source = 'eerstekamer';

\echo '== EK papers without any edge'
SELECT count(*) AS papers,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = d.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = d.id))
           AS without_edges
FROM documents d
WHERE d.source = 'eerstekamer';
