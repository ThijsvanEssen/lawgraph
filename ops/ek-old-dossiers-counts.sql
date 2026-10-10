-- The Kamerstukken of the Eerste Kamer of 1995-2006 and their dossiers: per year the papers, those that name a dossier
-- number, those whose dossier is in the graph, those PART_OF one, those without any edge, those that give the title of
-- their dossier (dossiertitel), and how many dossier numbers have no dossier. Read only; columns and edge indexes.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== EK papers 1995-2006 and their dossiers, per year'
SELECT left(p.date, 4) AS year,
       count(*) AS papers,
       count(p.dossier_number) AS with_number,
       count(*) FILTER (WHERE p.has_dossier) AS dossier_in_graph,
       count(*) FILTER (WHERE p.part_of) AS part_of_a_dossier,
       count(*) FILTER (WHERE p.alone) AS without_edges,
       count(*) FILTER (WHERE p.titled) AS with_dossier_title,
       count(DISTINCT p.dossier_number) FILTER (WHERE p.dossier_number IS NOT NULL AND NOT p.has_dossier)
           AS numbers_without_dossier
FROM (
    SELECT d.date, d.dossier_number,
           EXISTS (SELECT 1 FROM dossiers x WHERE x.id = 'dossiers/' || d.dossier_number) AS has_dossier,
           EXISTS (SELECT 1 FROM edges e WHERE e.from_id = d.id AND e.relation = 'PART_OF'
                     AND e.to_collection = 'dossiers') AS part_of,
           NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = d.id)
           AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = d.id) AS alone,
           coalesce(lg_str(d.pj_subject), '') <> '' AS titled
    FROM documents d
    WHERE d.source = 'eerstekamer' AND d.date >= '1995' AND d.date < '2007'
) p
GROUP BY ROLLUP (left(p.date, 4))
ORDER BY 1 ASC NULLS LAST;
