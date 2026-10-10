-- Read only: the EXPLAINS edges of memorandum sections (tk-mvt-articles) to articles a law
-- stores with their chapter ("11:2" of the Awb). Before the fix a change matched without
-- its chapter, so "artikel 2" or "artikel 1:3" found Awb 11:2 or 7:3; a full run of
-- tk-mvt-articles after the deploy puts such an edge back to the dossier, or removes it.
-- Run before and after that run: the measure is how `edges` in 2 drops (lawgraph_small:
-- 171 to 151). `heading_does_not_name_it` is a rough upper bound of the wrong ones: an
-- onderdeel heading names no number either (small: 101, of which 20 wrong).
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== 1. EXPLAINS of memoranda by source: section edges and dossier edges'
SELECT e.source, count(*) AS edges
FROM edges e
WHERE e.relation = 'EXPLAINS' AND e.from_collection = 'documents'
GROUP BY 1 ORDER BY 2 DESC;

\echo '== 2. Section edges to an article stored with its chapter, per law: all, and those whose heading does not name it (suspect)'
WITH target AS (
    SELECT e.key, coalesce(a.bwb_id, v.bwb_id) AS bwb_id,
           coalesce(a.article_number, v.article_number) AS number,
           e.doc -> 'meta' ->> 'heading' AS heading
    FROM edges e
    LEFT JOIN articles a ON a.id = e.to_id
    LEFT JOIN article_versions v ON v.id = e.to_id
    WHERE e.relation = 'EXPLAINS' AND e.source = 'mvt-section-linker'
)
SELECT bwb_id, count(*) AS edges,
       count(*) FILTER (WHERE strpos(coalesce(heading, ''), number) = 0) AS heading_does_not_name_it
FROM target
WHERE number LIKE '%:%'
GROUP BY 1 ORDER BY 2 DESC
LIMIT 15;
