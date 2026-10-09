-- Before and after `normalize eerstekamer-votes` with VOTED from EK factions: the EK decisions and
-- how many name factions, the VOTED edges into them per choice, and the EK factions without any
-- edge. Read only; counts only. EK decisions are few (thousands); their props are read for the
-- three name lists only. The names of no faction are in the log line of the step: "Wrote …
-- VOTED edges of EK factions; removed …; … names of no faction: …". Run with:
--   docker exec -i lawgraph-postgres psql -X -U lawgraph -d lawgraph < ek-faction-votes-counts.sql > ek-faction-votes-counts-output.txt 2>&1
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== EK decisions, and those that name a faction'
SELECT count(*) AS ek_decisions,
       count(*) FILTER (
           WHERE json_array_length(coalesce(d.props -> 'factions_for', '[]'::json))
               + json_array_length(coalesce(d.props -> 'factions_against', '[]'::json))
               + json_array_length(coalesce(d.props -> 'factions_noted', '[]'::json)) > 0
       ) AS naming_factions
FROM decisions d
WHERE lg_str(d.props -> 'chamber') = 'EK';

\echo '== VOTED into EK decisions, per choice'
SELECT e.doc -> 'meta' ->> 'choice' AS choice, count(*) AS edges,
       count(DISTINCT e.from_id) AS factions, count(DISTINCT e.to_id) AS decisions
FROM decisions d
JOIN edges e ON e.to_id = d.id AND e.relation = 'VOTED'
WHERE lg_str(d.props -> 'chamber') = 'EK'
GROUP BY 1
ORDER BY 1;

\echo '== EK factions without any edge'
SELECT count(*) AS ek_factions,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = f.id)
                          AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = f.id))
           AS without_edges
FROM factions f
WHERE lg_str(f.props -> 'chamber') = 'EK';
