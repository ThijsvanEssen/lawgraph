-- #453 before and after: the terms of the Eerste Kamer (checked, mismatches, stretches) and the stretches per
-- cabinet since 2003. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== terms'
SELECT t.start, t.election, t.checked, json_array_length(t.mismatches) AS mismatches,
       (SELECT count(*) FROM lg_ek_seats s WHERE s.term = t.start) AS stretches
FROM lg_ek_terms t
ORDER BY t.start ASC NULLS LAST;

\echo '== mismatches'
SELECT t.start, m.mismatch
FROM lg_ek_terms t, json_array_elements_text(t.mismatches) AS m(mismatch)
ORDER BY t.start ASC NULLS LAST;

\echo '== stretches per cabinet'
SELECT c.key, c.from_date, c.to_date, count(s.from_date) AS stretches, bool_and(t.checked) AS checked
FROM (SELECT key, lg_str(props -> 'from_date') AS from_date, lg_str(props -> 'to_date') AS to_date
      FROM cabinets) c
LEFT JOIN lg_ek_seats s
       ON s.from_date <= coalesce(c.to_date, '9999-12-31')
      AND (s.to_date IS NULL OR s.to_date >= c.from_date)
LEFT JOIN lg_ek_terms t ON t.start = s.term
WHERE c.from_date >= '2003-01-01'
GROUP BY c.key, c.from_date, c.to_date
ORDER BY c.from_date ASC NULLS LAST;
