-- #410 before and after: the factions with vacancies (a seat held by no member), and the periods. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== factions, those with vacancies, and the vacancy periods'
SELECT count(*) AS factions,
       count(*) FILTER (WHERE json_typeof(props -> 'vacancies') = 'array'
                          AND json_array_length(props -> 'vacancies') > 0) AS with_vacancies,
       coalesce(sum(json_array_length(props -> 'vacancies'))
                FILTER (WHERE json_typeof(props -> 'vacancies') = 'array'), 0) AS vacancy_periods
FROM factions;
