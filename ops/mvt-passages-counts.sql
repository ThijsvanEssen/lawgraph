-- Read only: the MvT passage per article (the passages of `explanations`). How many articles
-- have a passage now, and, in a sample of dossiers, what the bill onderdelen (A) and the
-- amendments (B) could add. An article is (bwb_id, stam_id): an EXPLAINS edge to the article
-- or to one of its versions. Sections 1 and the frame of 2 read edges and columns only; the
-- props (with the text) of a paper are read once, and only for the papers of the sampled
-- dossiers. SAMPLE below is the number of dossiers: 20 for the first run.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== 1. Explained articles: with a passage (meta.section_anchor), or per dossier only'
WITH ex AS (
    SELECT coalesce(a.bwb_id, v.bwb_id) AS bwb_id,
           coalesce(a.stam_id, v.stam_id) AS stam_id,
           coalesce(json_typeof(e.doc -> 'meta' -> 'section_anchor') = 'string', false) AS anchored
    FROM edges e
    LEFT JOIN articles a ON a.id = e.to_id
    LEFT JOIN article_versions v ON v.id = e.to_id
    WHERE e.relation = 'EXPLAINS' AND e.to_collection IN ('articles', 'article_versions')
),
per_article AS (
    SELECT bwb_id, stam_id, bool_or(anchored) AS anchored
    FROM ex WHERE stam_id IS NOT NULL GROUP BY 1, 2
)
SELECT count(*) AS explained,
       count(*) FILTER (WHERE anchored) AS with_passage,
       count(*) FILTER (WHERE NOT anchored) AS dossier_only
FROM per_article;

\echo '== 2. A sample of the dossiers of the articles explained per dossier only: per article, what could give it a passage'
\echo '   a = an MvT with "Artikel I, onderdeel A" headings and a bill with text; b = an amendment with that article heading (adopted or not)'
WITH ex AS (
    SELECT coalesce(a.bwb_id, v.bwb_id) AS bwb_id,
           coalesce(a.stam_id, v.stam_id) AS stam_id,
           lower(coalesce(a.article_number, v.article_number)) AS number,
           e.from_id AS document,
           coalesce(json_typeof(e.doc -> 'meta' -> 'section_anchor') = 'string', false) AS anchored
    FROM edges e
    LEFT JOIN articles a ON a.id = e.to_id
    LEFT JOIN article_versions v ON v.id = e.to_id
    WHERE e.relation = 'EXPLAINS' AND e.to_collection IN ('articles', 'article_versions')
),
dossier_only AS (
    SELECT bwb_id, stam_id, min(number) AS number, array_agg(DISTINCT document) AS docs
    FROM ex WHERE stam_id IS NOT NULL
    GROUP BY 1, 2 HAVING NOT bool_or(anchored)
),
article_dossiers AS (
    SELECT DISTINCT o.bwb_id, o.stam_id, o.number, u.document, p.to_id AS dossier
    FROM dossier_only o
    CROSS JOIN LATERAL unnest(o.docs) AS u(document)
    JOIN edges p ON p.from_id = u.document AND p.relation = 'PART_OF'
                AND p.to_collection = 'dossiers'
),
sample AS MATERIALIZED (
    SELECT DISTINCT dossier FROM article_dossiers ORDER BY dossier LIMIT 20  -- SAMPLE
),
papers AS MATERIALIZED (
    -- the props of each paper of the sample once (the cast detoasts them once)
    SELECT d.id, p.to_id AS dossier, d.kind,
           json_typeof(c.p -> 'text') = 'string' AS has_text,
           c.p ->> 'structure_quality' AS quality,
           CASE WHEN json_typeof(c.p -> 'sections') = 'array' THEN c.p -> 'sections'
                ELSE '[]'::json END AS sections
    FROM sample s
    JOIN edges p ON p.to_id = s.dossier AND p.relation = 'PART_OF'
                AND p.from_collection = 'documents'
    JOIN documents d ON d.id = p.from_id
    CROSS JOIN LATERAL (SELECT d.props::text::json AS p OFFSET 0) c
    WHERE d.kind LIKE 'Memorie van toelichting%' OR d.kind LIKE 'Voorstel van wet%'
       OR d.kind LIKE 'Amendement%'
),
memo AS (
    SELECT p.id, p.dossier,
           EXISTS (SELECT 1 FROM json_array_elements(p.sections) s
                   WHERE s ->> 'kind' = 'article' AND s ->> 'heading' ~* 'onderde') AS onderdeel_headings
    FROM papers p WHERE p.kind LIKE 'Memorie van toelichting%'
),
bill_dossiers AS (
    SELECT DISTINCT dossier FROM papers WHERE kind LIKE 'Voorstel van wet%' AND has_text
),
amendment_numbers AS (
    SELECT DISTINCT p.dossier, lower(r ->> 'number') AS number
    FROM papers p
    CROSS JOIN LATERAL json_array_elements(p.sections) s
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(s -> 'article_refs') = 'array' THEN s -> 'article_refs'
             ELSE '[]'::json END) r
    WHERE p.kind LIKE 'Amendement%'
),
classified AS (
    SELECT ad.bwb_id, ad.stam_id,
           bool_or(m.onderdeel_headings AND b.dossier IS NOT NULL) AS by_bill,
           bool_or(an.number IS NOT NULL) AS by_amendment
    FROM article_dossiers ad
    JOIN sample s ON s.dossier = ad.dossier
    LEFT JOIN memo m ON m.id = ad.document
    LEFT JOIN bill_dossiers b ON b.dossier = ad.dossier
    LEFT JOIN amendment_numbers an ON an.dossier = ad.dossier AND an.number = ad.number
    GROUP BY 1, 2
)
SELECT (SELECT count(DISTINCT dossier) FROM article_dossiers) AS dossiers,
       (SELECT count(*) FROM sample) AS sampled_dossiers,
       (SELECT count(*) FROM papers) AS papers_read,
       (SELECT count(*) FROM papers WHERE kind LIKE 'Voorstel van wet%') AS bills,
       (SELECT count(*) FROM papers WHERE kind LIKE 'Voorstel van wet%' AND has_text) AS bills_with_text,
       count(*) AS articles,
       count(*) FILTER (WHERE by_bill) AS a_bill_onderdeel,
       count(*) FILTER (WHERE by_amendment) AS b_amendment,
       count(*) FILTER (WHERE by_bill AND by_amendment) AS a_and_b,
       count(*) FILTER (WHERE NOT by_bill AND NOT by_amendment) AS neither
FROM classified;
