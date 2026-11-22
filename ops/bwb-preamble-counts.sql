-- The preamble (aanhef) of the regulations of the BWB: how many instruments have props.preamble, how many have
-- none, and how large it is. Read only.
--
-- `normalize bwb` writes preamble = null for a regulation without an aanhef, but the upsert (`lg_same`) does not
-- write an update that only adds a null, so a regulation without an aanhef mostly keeps the key absent: absent and
-- null both mean "no aanhef". A real gap is an absent preamble on a regulation that has a considerans text or
-- names its legal basis (sections 1 and 3: these should be about 0).
--
-- 1. regulations by kind and state of props.preamble: an object, null, absent, absent with a considerans.
-- 2. the size of the objects in bytes (the JSON text): p50, p95, max, and the sum.
-- 3. absent preamble on a regulation with a basis list.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. regulations by kind and props.preamble'
SELECT coalesce(i.props ->> 'kind', '(none)') AS kind,
       count(*) AS regulations,
       count(*) FILTER (WHERE json_typeof(i.props -> 'preamble') = 'object') AS with_preamble,
       count(*) FILTER (WHERE json_typeof(i.props -> 'preamble') = 'null') AS null_preamble,
       count(*) FILTER (WHERE i.props -> 'preamble' IS NULL) AS absent,
       count(*) FILTER (WHERE i.props -> 'preamble' IS NULL
                          AND coalesce(i.props ->> 'basis_preamble', '') <> '') AS absent_with_considerans
FROM instruments i
WHERE i.bwb_id IS NOT NULL
GROUP BY ROLLUP (coalesce(i.props ->> 'kind', '(none)'))
ORDER BY 2 DESC;

\echo '== 2. size of props.preamble in bytes'
SELECT count(*) AS preambles,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY n) AS p50,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY n) AS p95,
       max(n) AS max,
       sum(n) AS total
FROM (
    SELECT octet_length((i.props -> 'preamble')::text) AS n
    FROM instruments i
    WHERE i.bwb_id IS NOT NULL AND json_typeof(i.props -> 'preamble') = 'object'
) sizes;

\echo '== 3. absent preamble on a regulation that names its legal basis'
SELECT count(*) AS absent_with_basis
FROM instruments i
WHERE i.bwb_id IS NOT NULL AND i.props -> 'preamble' IS NULL
  AND json_array_length(coalesce(i.props -> 'basis', '[]'::json)) > 0;
