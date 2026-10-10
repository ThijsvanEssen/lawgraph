-- lg_instrument_names before and after its fill: the instruments, those with names kept, those without. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== instruments and their names kept'
SELECT count(*) AS instruments,
       count(n.id) AS with_names,
       count(*) FILTER (WHERE n.id IS NULL) AS without_names,
       count(*) FILTER (WHERE n.id IS NULL AND i.stub IS DISTINCT FROM TRUE) AS without_names_not_stub
FROM instruments i
LEFT JOIN lg_instrument_names n ON n.id = i.id;
