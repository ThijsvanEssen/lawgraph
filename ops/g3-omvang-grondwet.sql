-- Read-only measurement for B39 G3 (PR #1060), 3 of 3: every BASED_ON from a BWB regulation to
-- an article of the Grondwet (BWBR0001840), by origin (link of the source, or words) and the
-- period of the regulation: before the revision of 17 February 1983, until the first toestand
-- the BWB holds (2002-03-21), or after. Start of a regulation: the earliest of date_signed,
-- date_published and date_in_force.
--   gh workflow run ops --ref develop -f action=sql -f name=g3-omvang-grondwet
-- Read only; counts only.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

WITH gw AS MATERIALIZED (
    SELECT e.from_id, e.confidence
    FROM articles a
    JOIN edges e ON e.to_id = a.id AND e.relation = 'BASED_ON'
    WHERE a.bwb_id = 'BWBR0001840'
      AND e.source = 'bwb-grondslagen-linker'
)
SELECT CASE WHEN g.confidence >= 1 THEN 'link' ELSE 'tekst' END AS herkomst,
       CASE WHEN s.start IS NULL THEN 'zonder datum'
            WHEN s.start < '1983-02-17' THEN 'voor 1983-02-17'
            WHEN s.start < '2002-03-21' THEN '1983 tot 2002-03-21'
            ELSE 'vanaf 2002-03-21' END AS periode,
       count(DISTINCT g.from_id) AS regelingen, count(*) AS edges
FROM gw g
JOIN instruments i ON i.id = g.from_id
CROSS JOIN LATERAL (
    SELECT LEAST(NULLIF(left(btrim(i.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_in_force'), 10), '')) AS start
) s
GROUP BY 1, 2
ORDER BY 1 NULLS FIRST, 2 NULLS FIRST;
