-- The preamble (aanhef) of the regulations of the BWB: how many instruments have props.preamble, how many were read
-- without one, how many were not normalized since the aanhef came (no key), and how large it is. Read only; run
-- before and after `normalize bwb` over all (ops/renormalize-bwb.sh).
--
-- 1. regulations (bwb_id) by state of props.preamble: an object, null (read, the regulation has none), absent.
-- 2. the size of the objects in bytes (the JSON text): p50, p95, max, and the sum.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. regulations by props.preamble'
SELECT count(*) AS regulations,
       count(*) FILTER (WHERE json_typeof(i.props -> 'preamble') = 'object') AS with_preamble,
       count(*) FILTER (WHERE json_typeof(i.props -> 'preamble') = 'null') AS without_preamble,
       count(*) FILTER (WHERE i.props -> 'preamble' IS NULL) AS not_yet_read
FROM instruments i
WHERE i.bwb_id IS NOT NULL;

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
