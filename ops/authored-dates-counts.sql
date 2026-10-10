-- lg_authored before and after its dates are kept: whether it is dated, whether the index the cabinet counts read is
-- there and valid, its rows with and without a date and a capacity, and once dated the rows without a date whose paper
-- or case has one (expected: none). Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== dated'
SELECT dated_at FROM lg_authored_dated;

\echo '== the index (built beforehand with CREATE INDEX CONCURRENTLY; must be valid)'
SELECT indexrelid::regclass AS index, indisvalid FROM pg_index
WHERE indexrelid::regclass::text = 'lg_authored_member_date';

\echo '== rows, with a date, with a capacity'
SELECT count(*) AS rows, count(date) AS dated, count(capacity) AS with_capacity,
       count(*) FILTER (WHERE lg_str(meta -> 'capacity') IS NOT NULL) AS capacity_in_meta
FROM lg_authored;

\echo '== rows without a date, per collection signed'
SELECT split_part(document_id, '/', 1) AS collection, count(*) AS undated
FROM lg_authored WHERE date IS NULL
GROUP BY 1 ORDER BY 1;

\echo '== once dated: rows without a date whose paper or case has one (expected: none)'
SELECT split_part(a.document_id, '/', 1) AS collection, count(*) AS missing
FROM lg_authored a
LEFT JOIN documents d ON d.id = a.document_id
LEFT JOIN cases k ON k.id = a.document_id
WHERE EXISTS (SELECT 1 FROM lg_authored_dated)
  AND a.date IS NULL AND coalesce(d.date, lg_str(k.props -> 'date')) IS NOT NULL
GROUP BY 1 ORDER BY 1;
