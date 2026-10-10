-- Read-only (Back-end #3, 2026-10-10). How many Staatscourant regulations an exact SAME_AS to the BWB
-- publication of the same official id (stcrt_<id> ↔ instruments/<id>) would link. Key columns and edge
-- indexes only, no props.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off
\echo '== regulations and the BWB publication of the same id'
SELECT count(*) AS regelingen,
       count(*) FILTER (WHERE alone) AS without_edges,
       count(i.id) AS with_bwb_publication,
       count(i.id) FILTER (WHERE alone) AS without_edges_with_bwb_publication,
       count(i.id) FILTER (WHERE alone AND EXISTS (SELECT 1 FROM edges e WHERE e.from_id = i.id))
           AS of_those_publication_has_edges
FROM (
    SELECT d.id, d.key,
           NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = d.id)
           AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = d.id) AS alone
    FROM documents d
    WHERE d.source = 'staatscourant' AND d.key LIKE 'stcrt\_stcrt\_%'
) d
LEFT JOIN instruments i ON i.id = 'instruments/' || substr(d.key, 7);
\echo '== per year'
SELECT split_part(d.key, '_', 3) AS year, count(*) AS regelingen, count(i.id) AS with_bwb_publication
FROM documents d
LEFT JOIN instruments i ON i.id = 'instruments/' || substr(d.key, 7)
WHERE d.source = 'staatscourant' AND d.key LIKE 'stcrt\_stcrt\_%'
GROUP BY 1 ORDER BY 1 DESC NULLS LAST;
\echo '== BWB publications in the Staatscourant without a regulation document'
SELECT count(*) AS bwb_stcrt_publications, count(*) FILTER (WHERE d.id IS NULL) AS without_document
FROM instruments i
LEFT JOIN documents d ON d.id = 'documents/stcrt_' || i.key
WHERE i.key LIKE 'stcrt\_%' AND i.kind = 'publicatie';
