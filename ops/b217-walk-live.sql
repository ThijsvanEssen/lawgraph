-- B217: where lg_neighborhood (0.80.50) spends its time on prod, read only: per statement inside the function
-- (auto_explain, those of 20 ms or more, with what they read), for the BW and the Grondwet, depth 3, cap 200,
-- with the arguments of the route (props=canvas). Each twice: the first read as it comes, the second from cache.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off
\timing on
LOAD 'auto_explain';
SET auto_explain.log_min_duration = 20;
SET auto_explain.log_nested_statements = on;
SET auto_explain.log_analyze = on;
SET auto_explain.log_buffers = on;
SET auto_explain.log_timing = on;
SET client_min_messages = log;

\echo '== instruments/bwbr0005289 depth 3, first'
SELECT cardinality(lg_neighborhood('instruments/bwbr0005289', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}')) AS nodes;
\echo '== instruments/bwbr0005289 depth 3, second'
SELECT cardinality(lg_neighborhood('instruments/bwbr0005289', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}')) AS nodes;
\echo '== instruments/bwbr0001840 depth 3, first'
SELECT cardinality(lg_neighborhood('instruments/bwbr0001840', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}')) AS nodes;
\echo '== instruments/bwbr0001840 depth 3, second'
SELECT cardinality(lg_neighborhood('instruments/bwbr0001840', 3, 200, NULL, NULL, true, true, NULL, '{activities,annexes,article_versions,articles,cabinets,cases,commitments,committees,decisions,documents,dossiers,factions,instrument_versions,instruments,judgments,members,ministries}', NULL, '{"MEMBER_OF factions","SERVED_IN cabinets"}')) AS nodes;
