-- The pages of the motions of the Eerste Kamer and what they bring, before and after: the motions the votes name, the
-- pages stored, the motions of the Eerste Kamer with what they ask and with signers, the signers with and without a
-- member, and the AUTHORED edges from the pages. Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== motions the votes name, pages stored'
SELECT (SELECT count(DISTINCT d.props ->> 'motion_url') FROM decisions d
        WHERE 'EK' = ANY(d.labels) AND d.props ->> 'kind' = 'Motie') AS motions_voted,
       (SELECT count(*) FROM raw_sources WHERE source = 'eerstekamer' AND kind = 'ek-motion-html') AS pages;

\echo '== motions of the Eerste Kamer, with what they ask, with signers'
SELECT count(*) AS motions,
       count(*) FILTER (WHERE d.props ->> 'summary' IS NOT NULL) AS with_summary,
       count(*) FILTER (WHERE json_typeof(d.props -> 'actors') = 'array') AS with_signers
FROM documents d
WHERE 'EK' = ANY(d.labels) AND d.props ->> 'kind' = 'Motie';

\echo '== signers, with and without a member'
SELECT count(*) AS signers,
       count(*) FILTER (WHERE a ->> 'person_id' IS NOT NULL) AS with_member,
       count(*) FILTER (WHERE a ->> 'person_id' IS NULL) AS without_member
FROM documents d, json_array_elements(
    CASE WHEN json_typeof(d.props -> 'actors') = 'array' THEN d.props -> 'actors' ELSE '[]'::json END) AS a
WHERE 'EK' = ANY(d.labels) AND d.props ->> 'kind' = 'Motie';

\echo '== AUTHORED from the pages of the motions'
SELECT count(*) AS edges, count(DISTINCT e.to_id) AS motions, count(DISTINCT e.from_id) AS members
FROM edges e
WHERE e.relation = 'AUTHORED' AND e.source = 'eerstekamer-motions';
