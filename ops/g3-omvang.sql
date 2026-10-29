-- Read-only measurement for B39 G3 (PR #1060): how many BASED_ON edges from words
-- ("gelet op artikel 86 der Grondwet") `semantic bwb-grondslagen` would no longer write, per
-- criterion. The start of a regulation or a law is the earliest of date_signed, date_published
-- and date_in_force; a regulation without one drops nothing. Counted are the edges of the last
-- run: a reference whose article is not in the graph has no edge and is not counted.
--   eerste_toestand  the regulation is older than the first toestand of the law in
--                    instrument_versions (#1060 so far; a law with a toestand without
--                    valid_from drops nothing).
--   wet_later        the regulation is older than the law it names: the name resolved to a
--                    law that did not exist yet.
--   nummer_nieuw     eerste_toestand, and the number names no article of the oldest toestand.
--   voor_1983        Grondwet only: the regulation is from before 17 February 1983.
-- Second table: the regulations behind eerste_toestand of a law whose first toestand is from
-- 2005 on (a new law, BWBR0052871). Third: the Grondwet per origin and period.
--   gh workflow run ops --ref develop -f action=sql -f name=g3-omvang
-- Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

-- Row "(alle wetten)" is the total; then the top 30 laws by eerste_toestand and every law
-- wet_later or nummer_nieuw drops an edge of.
WITH worded AS (
    SELECT e.from_id, upper(a.bwb_id) AS law, a.article_number,
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
first AS (
    SELECT upper(bwb_id) AS law,
           CASE WHEN bool_or(valid_from IS NULL) THEN NULL
                ELSE left(min(valid_from), 10) END AS first_from
    FROM instrument_versions
    WHERE upper(bwb_id) IN (SELECT law FROM worded)
    GROUP BY upper(bwb_id)
),
law AS (
    SELECT upper(l.props ->> 'bwb_id') AS law,
           LEAST(NULLIF(left(btrim(l.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(l.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(l.props ->> 'date_in_force'), 10), '')) AS law_start
    FROM instruments l
    WHERE l.key IN (SELECT lower(law) FROM worded)
),
judged AS (
    SELECT w.law, w.from_id, f.first_from, l.law_start,
           w.start < f.first_from AS eerste_toestand,
           w.start < l.law_start AS wet_later,
           w.start < f.first_from AND NOT EXISTS (
               SELECT 1 FROM article_versions v
               WHERE upper(v.bwb_id) = w.law AND v.article_number = w.article_number
                 AND left(v.valid_from, 10) <= f.first_from
                 AND (v.valid_until IS NULL OR left(v.valid_until, 10) > f.first_from)
           ) AS nummer_nieuw,
           w.law = 'BWBR0001840' AND w.start < '1983-02-17' AS voor_1983
    FROM worded w
    LEFT JOIN first f USING (law)
    LEFT JOIN law l USING (law)
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
       wet_later, nummer_nieuw, voor_1983, eerste_van, wet_van
FROM (
    SELECT *, CASE WHEN law IS NULL THEN 0
                   ELSE row_number() OVER (ORDER BY law IS NULL, eerste_toestand DESC, law)
              END AS rang
    FROM per_law
) r
WHERE rang <= 30 OR wet_later > 0 OR nummer_nieuw > 0
ORDER BY rang, law;

WITH worded AS (
    SELECT e.from_id, upper(a.bwb_id) AS law,
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
first AS (
    SELECT upper(bwb_id) AS law, left(min(valid_from), 10) AS first_from
    FROM instrument_versions
    WHERE upper(bwb_id) IN (SELECT law FROM worded)
    GROUP BY upper(bwb_id)
    HAVING left(min(valid_from), 10) >= '2005'
)
SELECT w.law, f.first_from, i.props ->> 'bwb_id' AS regeling, w.start,
       i.props ->> 'date_signed' AS ondertekend, i.props ->> 'date_in_force' AS in_werking,
       left(i.props ->> 'title', 60) AS titel, count(*) AS edges
FROM worded w
JOIN first f USING (law)
JOIN instruments i ON i.id = w.from_id
WHERE w.start < f.first_from
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY w.law, w.start
LIMIT 60;

SELECT CASE WHEN e.confidence >= 1 THEN 'link' ELSE 'tekst' END AS herkomst,
       CASE WHEN s.start IS NULL THEN 'zonder datum'
            WHEN s.start < '1983-02-17' THEN 'voor 1983-02-17'
            WHEN s.start < '2002-03-21' THEN '1983 tot 2002-03-21'
            ELSE 'vanaf 2002-03-21' END AS periode,
       count(DISTINCT e.from_id) AS regelingen, count(*) AS edges
FROM edges e
JOIN articles a ON a.id = e.to_id
JOIN instruments i ON i.id = e.from_id
CROSS JOIN LATERAL (
    SELECT LEAST(NULLIF(left(btrim(i.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_in_force'), 10), '')) AS start
) s
WHERE e.relation = 'BASED_ON' AND e.source = 'bwb-grondslagen-linker'
  AND upper(a.bwb_id) = 'BWBR0001840'
GROUP BY 1, 2
ORDER BY 1, 2;
