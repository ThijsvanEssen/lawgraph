-- semantic bwb-publications before and after: per source the papers of the Staatsblad and the Staatscourant, those
-- with the BWB publication of the same official id, those SAME_AS it, and those without any edge. Read only; key
-- columns and edge indexes, no props.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== papers, their BWB publication, SAME_AS and loose'
SELECT p.source,
       count(*) AS papers,
       count(i.id) AS with_bwb_publication,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM edges e WHERE e.from_id = p.id AND e.relation = 'SAME_AS')) AS same_as,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = p.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = p.id)) AS without_edges
FROM (
    SELECT d.id, d.source, substr(d.key, length(x.prefix) + 1) AS publication
    FROM (VALUES ('staatsblad', 'stb_'), ('staatscourant', 'stcrt_')) AS x(source, prefix)
    JOIN documents d ON d.source = x.source AND starts_with(d.key, x.prefix || x.prefix)
) p
LEFT JOIN instruments i ON i.id = 'instruments/' || p.publication AND i.kind = 'publicatie'
GROUP BY p.source
ORDER BY p.source ASC NULLS LAST;
