-- lg_authored before and after its fill: whether it is filled, its rows, and the signatures of members it lacks.
-- Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== filled'
SELECT filled_at FROM lg_authored_state;

\echo '== signatures of members and those kept'
SELECT (SELECT count(*) FROM edges e WHERE e.relation = 'AUTHORED' AND e.from_collection = 'members') AS signatures,
       (SELECT count(*) FROM lg_authored) AS kept,
       (SELECT count(*) FROM edges e
        WHERE e.relation = 'AUTHORED' AND e.from_collection = 'members'
          AND NOT EXISTS (SELECT 1 FROM lg_authored a WHERE a.edge_key = e.key)) AS not_kept;
