SET default_transaction_read_only = on;
-- The stored BWB toestanden by whether their meta holds the Staatsblad publication (E16), and the publications.
SELECT CASE
         WHEN (doc -> 'meta')::jsonb ? 'staatsblad_ref' IS NOT TRUE THEN 'no key'
         WHEN doc -> 'meta' ->> 'staatsblad_ref' IS NULL THEN 'null'
         ELSE 'ref'
       END AS staatsblad_ref,
       count(*)
FROM raw_sources
WHERE source = 'bwb' AND kind = 'bwb-toestand-xml'
GROUP BY 1 ORDER BY 1;
SELECT kind, count(*) FROM raw_sources WHERE source = 'staatsblad' GROUP BY 1 ORDER BY 1;
