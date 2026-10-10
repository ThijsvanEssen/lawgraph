-- lg_faction_votes before and after its fill: whether it is filled, its rows, and the votes of factions it lacks.
-- Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== filled'
SELECT filled_at FROM lg_faction_votes_state;

\echo '== votes of factions and those kept'
SELECT (SELECT count(*) FROM edges e WHERE e.relation = 'VOTED' AND e.from_collection = 'factions') AS faction_votes,
       (SELECT count(*) FROM lg_faction_votes) AS kept,
       (SELECT count(*) FROM edges e
        WHERE e.relation = 'VOTED' AND e.from_collection = 'factions'
          AND EXISTS (SELECT 1 FROM decisions d WHERE d.id = e.to_id)
          AND NOT EXISTS (SELECT 1 FROM lg_faction_votes v WHERE v.edge_key = e.key)) AS not_kept;
