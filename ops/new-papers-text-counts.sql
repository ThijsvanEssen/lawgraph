-- Read only: of the Tweede Kamer papers of the last 14 days, per day, how many have their
-- text, and where the others stand. `retrieve tk-content` fetches the XML of papers whose
-- kind contains toelichting, motie, amendement, voorstel van wet or nota van wijziging
-- ("eligible"), that have a dossier number and a number in it (their address
-- kst-<dossier>-<n>); the repository has a new paper's XML about two working days after its
-- PDF; a fresh paper it answered 404 for is asked again after 3 days. Only the nightly
-- fetches it (no poll does), and `semantic tk-dictum` then writes a motion's dictum.
-- The text is read only for the eligible papers of these 14 days (a few hundred).
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== Per day: papers, eligible, with text; of the eligible without text, why; motions with dictum'
WITH recent AS (
    SELECT d.id, left(d.date, 10) AS day, d.kind,
           d.kind ~* '(toelichting|motie|amendement|voorstel van wet|nota van wijziging)'
               AS eligible
    FROM documents d
    WHERE 'TK' = ANY(d.labels)
      AND d.date >= to_char(current_date - 14, 'YYYY-MM-DD')
),
eligible AS (
    SELECT r.id, r.day, r.kind,
           json_typeof(c.p -> 'text') = 'string' AS has_text,
           json_typeof(c.p -> 'dictum') = 'string' AS has_dictum,
           CASE WHEN lg_truthy(c.p -> 'dossier_number') AND lg_truthy(c.p -> 'sequence')
                THEN 'kst-' || (c.p ->> 'dossier_number')
                     || CASE WHEN lg_truthy(c.p -> 'dossier_suffix')
                             THEN '-' || (c.p ->> 'dossier_suffix') ELSE '' END
                     || '-' || (c.p ->> 'sequence')
           END AS identifier
    FROM recent r
    JOIN documents d ON d.id = r.id
    CROSS JOIN LATERAL (SELECT d.props::text::json AS p OFFSET 0) c
    WHERE r.eligible
),
raw AS (
    SELECT rs.external_id, rs.kind
    FROM raw_sources rs
    WHERE rs.source = 'tk'
      AND rs.kind IN ('tk-kamerstuk-xml', 'tk-kamerstuk-xml-missing')
      AND rs.external_id IN (SELECT identifier FROM eligible WHERE identifier IS NOT NULL)
),
per_paper AS (
    SELECT e.*,
           EXISTS (SELECT 1 FROM raw x WHERE x.external_id = e.identifier
                   AND x.kind = 'tk-kamerstuk-xml') AS xml_stored,
           EXISTS (SELECT 1 FROM raw x WHERE x.external_id = e.identifier
                   AND x.kind = 'tk-kamerstuk-xml-missing') AS answered_404
    FROM eligible e
)
SELECT r.day,
       count(*) AS papers,
       count(*) FILTER (WHERE r.eligible) AS eligible,
       count(p.id) FILTER (WHERE p.has_text) AS with_text,
       count(p.id) FILTER (WHERE NOT coalesce(p.has_text, false) AND p.identifier IS NULL) AS no_address,
       count(p.id) FILTER (WHERE NOT coalesce(p.has_text, false) AND p.xml_stored) AS xml_not_read_yet,
       count(p.id) FILTER (WHERE NOT coalesce(p.has_text, false) AND NOT p.xml_stored AND p.answered_404) AS answered_404,
       count(p.id) FILTER (WHERE NOT coalesce(p.has_text, false) AND p.identifier IS NOT NULL
                           AND NOT p.xml_stored AND NOT p.answered_404) AS not_asked_yet,
       count(*) FILTER (WHERE r.kind ILIKE 'motie%') AS motions,
       count(p.id) FILTER (WHERE p.kind ILIKE 'motie%' AND p.has_dictum) AS motions_with_dictum
FROM recent r
LEFT JOIN per_paper p ON p.id = r.id
GROUP BY r.day
ORDER BY r.day DESC;
