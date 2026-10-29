-- Read-only measurement for B39 G3 (PR #1060), 1 of 3: per law named in words, how many
-- BASED_ON edges `semantic bwb-grondslagen` would no longer write, per criterion. Row
-- "(alle wetten)" is the total. The start of a regulation or a law is the earliest of
-- date_signed, date_published and date_in_force; a regulation without one drops nothing.
-- Counted are the edges of the last run: a reference without an edge is not counted.
--   eerste_toestand  older than the first toestand of the law (the criterion #1060 dropped)
--   wet_later        older than the law it names (#1060: the text is dated, `on=`)
--   nummer_nieuw     eerste_toestand, and the first toestand has no article of the number
--                    (#1060: the gap `not_in_first_version`)
--   voor_1983        Grondwet only: from before 17 February 1983 (for comparison)
-- Each worded edge is read once; the first toestand and its numbers once per law.
--   gh workflow run ops --ref develop -f action=sql -f name=g3-omvang-per-wet
-- Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

WITH worded AS MATERIALIZED (
    SELECT e.from_id, a.bwb_id AS law, a.article_number,
           LEAST(NULLIF(left(btrim(i.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_in_force'), 10), '')) AS start
    FROM edges e
    JOIN instruments i ON i.id = e.from_id
    JOIN articles a ON a.id = e.to_id
    WHERE e.relation = 'BASED_ON'
      AND e.source = 'bwb-grondslagen-linker'
      AND e.confidence < 1
),
laws AS MATERIALIZED (
    SELECT DISTINCT law FROM worded
),
first AS MATERIALIZED (
    SELECT v.bwb_id AS law,
           CASE WHEN bool_or(v.valid_from IS NULL) THEN NULL
                ELSE left(min(v.valid_from), 10) END AS first_from
    FROM instrument_versions v
    JOIN laws ON laws.law = v.bwb_id
    GROUP BY v.bwb_id
),
law_start AS MATERIALIZED (
    SELECT laws.law,
           LEAST(NULLIF(left(btrim(l.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(l.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(l.props ->> 'date_in_force'), 10), '')) AS law_start
    FROM laws
    JOIN instruments l ON l.key = lower(laws.law)
),
-- the (law, number) pairs eerste_toestand names, each looked up once in the first toestand
asked AS MATERIALIZED (
    SELECT DISTINCT w.law, w.article_number, f.first_from
    FROM worded w
    JOIN first f USING (law)
    WHERE w.start < f.first_from AND w.article_number IS NOT NULL
),
known AS MATERIALIZED (
    SELECT q.law, q.article_number
    FROM asked q
    WHERE EXISTS (
        SELECT 1 FROM article_versions v
        WHERE v.bwb_id = q.law AND v.article_number = q.article_number
          AND left(v.valid_from, 10) <= q.first_from
          AND (v.valid_until IS NULL OR left(v.valid_until, 10) > q.first_from)
    )
),
judged AS (
    SELECT w.law, w.from_id, f.first_from, s.law_start,
           coalesce(w.start < f.first_from, false) AS eerste_toestand,
           coalesce(w.start < s.law_start, false) AS wet_later,
           coalesce(w.start < f.first_from, false) AND k.law IS NULL AS nummer_nieuw,
           w.law = 'BWBR0001840' AND coalesce(w.start < '1983-02-17', false) AS voor_1983
    FROM worded w
    LEFT JOIN first f USING (law)
    LEFT JOIN law_start s USING (law)
    LEFT JOIN known k USING (law, article_number)
),
per_law AS (
    SELECT law,
           count(*) AS tekst_totaal,
           count(*) FILTER (WHERE eerste_toestand) AS eerste_toestand,
           count(DISTINCT from_id) FILTER (WHERE eerste_toestand) AS regelingen,
           count(*) FILTER (WHERE wet_later) AS wet_later,
           count(*) FILTER (WHERE nummer_nieuw) AS nummer_nieuw,
           count(*) FILTER (WHERE voor_1983) AS voor_1983,
           min(first_from) AS eerste_van,
           min(law_start) AS wet_van
    FROM judged
    GROUP BY GROUPING SETS ((law), ())
)
SELECT coalesce(law, '(alle wetten)') AS law, tekst_totaal, eerste_toestand, regelingen,
       wet_later, nummer_nieuw, voor_1983,
       CASE WHEN law IS NOT NULL THEN eerste_van END AS eerste_van,
       CASE WHEN law IS NOT NULL THEN wet_van END AS wet_van
FROM (
    SELECT *, CASE WHEN law IS NULL THEN 0
                   ELSE row_number() OVER (ORDER BY law IS NULL, eerste_toestand DESC,
                                                    law NULLS FIRST)
              END AS rang
    FROM per_law
) r
WHERE rang <= 30 OR wet_later > 0 OR nummer_nieuw > 0
ORDER BY rang, law NULLS FIRST;
