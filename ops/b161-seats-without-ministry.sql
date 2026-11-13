-- Read only (B161): the posts whose seat sits in no ministry after `normalize rijksoverheid`, with the
-- function as the Rijksoverheid page writes it and why the sources gave no ministry; and the records of
-- `retrieve staatscourant-posts` for those posts (the ministries that issued the publications naming them).
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

\echo '== posts without a ministry in their seat'
SELECT f ->> 'seat' AS seat, f ->> 'function' AS function, f ->> 'cabinet' AS cabinet, f ->> 'name' AS name,
       f ->> 'from_date' AS from_date, f ->> 'to_date' AS to_date, f ->> 'ministry' AS ministry,
       f ->> 'ministry_source' AS source, f ->> 'ministry_missing' AS missing
FROM members m, json_array_elements(m.props -> 'government_functions') f
WHERE split_part(f ->> 'seat', '/', 1)
      IN ('minister', 'minister_zonder_portefeuille', 'staatssecretaris', 'onbekend')
   OR f ->> 'ministry_missing' IS NOT NULL
ORDER BY 1, 5;

\echo '== staatscourant-posts records of posts the sources gave no ministry'
SELECT r.external_id, left((r.doc -> 'payload_json' -> 'creators')::text, 400) AS creators, r.fetched_at
FROM raw_sources r
WHERE r.source = 'staatscourant' AND r.kind = 'stcrt-post-creators-json'
  AND EXISTS (
    SELECT 1
    FROM members m, json_array_elements(m.props -> 'government_functions') f
    WHERE f ->> 'ministry_missing' IS NOT NULL
      AND split_part(r.external_id, '|', 1) = lower(regexp_replace(f ->> 'function', '[^[:alnum:]]+', ' ', 'g'))
  )
ORDER BY 1;
