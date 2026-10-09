-- #413 before and after: the EXPLAINS of the Staatsblad notes per match type, and the notes without any edge
-- (the section of linker-fixes-counts.sql of post-0.79.28); the second counts every document of the source
-- staatsblad, notes and others. Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== Staatsblad notes: EXPLAINS per match type, and those without any edge'
SELECT e.doc -> 'meta' ->> 'match_type' AS match_type, count(*) AS edges
FROM edges e
WHERE e.relation = 'EXPLAINS' AND e.source = 'staatsblad-nvt-linker'
GROUP BY 1
ORDER BY 1;

SELECT count(*) AS staatsblad_documents,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = d.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = d.id))
           AS without_edges
FROM documents d
WHERE d.source = 'staatsblad';
