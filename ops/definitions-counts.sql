-- #414 before and after: the regulations with a row of definitions of their own (lg_instrument_definitions).
-- Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== regulations with a definitions row'
SELECT count(*) AS regulations, count(DISTINCT bwb_id) AS bwb_ids FROM lg_instrument_definitions;
