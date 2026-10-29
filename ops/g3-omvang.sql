-- Read-only measurement for B39 G3 (PR #1060): how many BASED_ON edges from words
-- ("gelet op artikel 86 der Grondwet") `semantic bwb-grondslagen` would no longer write, because
-- the regulation is older than the first toestand the BWB holds of the law it names.
-- #1060 drops a worded reference when the start of the regulation (earliest of date_signed,
-- date_published, date_in_force) is before the earliest valid_from of the law in
-- instrument_versions; a law with a toestand without a valid_from, or a regulation without a
-- date, drops nothing. This counts the edges of the last run that meet that condition: a
-- reference whose article is not in the graph has no edge and is not counted (a lower bound).
--   gh workflow run ops --ref develop -f action=sql -f name=g3-omvang
-- Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

-- Row "(alle wetten)" is the total; the rest is per law named, top 25 by edges_weg.
WITH worded AS (
    SELECT e.from_id, a.bwb_id AS law,
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
    SELECT bwb_id,
           CASE WHEN bool_or(valid_from IS NULL) THEN NULL
                ELSE left(min(valid_from), 10) END AS first_from
    FROM instrument_versions
    GROUP BY bwb_id
),
per_law AS (
    SELECT w.law,
           count(*) FILTER (WHERE w.start < f.first_from) AS edges_weg,
           count(DISTINCT w.from_id) FILTER (WHERE w.start < f.first_from) AS regelingen_weg,
           count(*) AS edges_tekst_totaal,
           min(f.first_from) AS eerste_toestand
    FROM worded w
    LEFT JOIN first f ON f.bwb_id = upper(w.law)
    GROUP BY w.law
),
total AS (
    SELECT '(alle wetten)' AS law,
           (SELECT count(*) FROM worded w LEFT JOIN first f ON f.bwb_id = upper(w.law)
            WHERE w.start < f.first_from) AS edges_weg,
           (SELECT count(DISTINCT w.from_id) FROM worded w LEFT JOIN first f ON f.bwb_id = upper(w.law)
            WHERE w.start < f.first_from) AS regelingen_weg,
           (SELECT count(*) FROM worded) AS edges_tekst_totaal,
           NULL::text AS eerste_toestand
),
top AS (
    SELECT * FROM per_law ORDER BY edges_weg DESC, law LIMIT 25
)
SELECT law, edges_weg, regelingen_weg, edges_tekst_totaal, eerste_toestand
FROM (SELECT total.*, 0 AS rang FROM total
               UNION ALL
               SELECT top.*, 1 FROM top) r
ORDER BY rang, edges_weg DESC, law;
