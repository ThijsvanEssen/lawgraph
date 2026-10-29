-- Read-only measurement for B39 G3 (PR #1060), 2 of 3: the regulations whose words name a law
-- whose first toestand is from 2005 on (a new law, BWBR0052871) while they are older than it:
-- signed before the law came into force, or named a law that came later.
-- Start of a regulation: the earliest of date_signed, date_published and date_in_force.
--   gh workflow run ops --ref develop -f action=sql -f name=g3-omvang-nieuwe-wetten
-- Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
\pset pager off

WITH worded AS MATERIALIZED (
    SELECT e.from_id, a.bwb_id AS law
    FROM edges e
    JOIN articles a ON a.id = e.to_id
    WHERE e.relation = 'BASED_ON'
      AND e.source = 'bwb-grondslagen-linker'
      AND e.confidence < 1
),
first AS MATERIALIZED (
    SELECT v.bwb_id AS law, left(min(v.valid_from), 10) AS first_from
    FROM instrument_versions v
    WHERE v.bwb_id IN (SELECT law FROM worded)
    GROUP BY v.bwb_id
    HAVING left(min(v.valid_from), 10) >= '2005'
),
counted AS (
    SELECT w.law, f.first_from, w.from_id, count(*) AS edges
    FROM worded w
    JOIN first f USING (law)
    GROUP BY 1, 2, 3
)
SELECT c.law, c.first_from, i.props ->> 'bwb_id' AS regeling, s.start,
       i.props ->> 'date_signed' AS ondertekend, i.props ->> 'date_in_force' AS in_werking,
       left(i.props ->> 'title', 60) AS titel, c.edges
FROM counted c
JOIN instruments i ON i.id = c.from_id
CROSS JOIN LATERAL (
    SELECT LEAST(NULLIF(left(btrim(i.props ->> 'date_signed'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_published'), 10), ''),
                 NULLIF(left(btrim(i.props ->> 'date_in_force'), 10), '')) AS start
) s
WHERE s.start < c.first_from
ORDER BY c.law NULLS FIRST, s.start NULLS FIRST, regeling NULLS FIRST
LIMIT 60;
