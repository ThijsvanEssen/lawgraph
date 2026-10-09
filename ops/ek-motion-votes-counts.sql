-- ek-motion-votes-counts.sql: the votes of the Eerste Kamer before and after V4(a), read-only.
--
-- Written by Back-end #1 (2026-10-09) for the Orchestrator. V4(a) reads the list of every vote
-- (filter=alles) instead of the bills alone, which showed a vote on a motion as one on its bill.
-- Run before the retrieve and again after `semantic tk-dossier-outcomes`:
--     PGOPTIONS="-c default_transaction_read_only=on" psql "$DSN" -f ek-motion-votes-counts.sql
-- Only SELECTs; every one through an index or over the EK decisions alone (a few thousand).

\echo '== EK vote decisions per kind (null: on a bill; Motie: on a motion)'
SELECT coalesce(lg_str(props -> 'kind'), '(bill)') AS kind, count(*)
FROM decisions
WHERE lg_str(props -> 'chamber') = 'EK' AND starts_with(key, 'ek_')
GROUP BY 1 ORDER BY 1;

\echo '== EK vote decisions with a letter in their key (votes on a motion) and without'
SELECT key ~ '_[a-z]{1,3}$' AS on_a_motion, count(*)
FROM decisions
WHERE lg_str(props -> 'chamber') = 'EK' AND starts_with(key, 'ek_')
GROUP BY 1 ORDER BY 1;

\echo '== EK vote decisions per year'
SELECT left(date, 4) AS year, count(*) FILTER (WHERE lg_str(props -> 'kind') = 'Motie') AS motions,
       count(*) FILTER (WHERE lg_str(props -> 'kind') IS DISTINCT FROM 'Motie') AS bills
FROM decisions
WHERE lg_str(props -> 'chamber') = 'EK' AND starts_with(key, 'ek_')
GROUP BY 1 ORDER BY 1;

\echo '== VOTED into EK vote decisions, per choice, bill and motion'
SELECT CASE WHEN lg_str(d.props -> 'kind') = 'Motie' THEN 'motion' ELSE 'bill' END AS on_,
       e.doc -> 'meta' ->> 'choice' AS choice, count(*)
FROM decisions d
JOIN edges e ON e.to_id = d.id AND e.relation = 'VOTED'
WHERE lg_str(d.props -> 'chamber') = 'EK' AND starts_with(d.key, 'ek_')
GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== EK votes on a motion ABOUT their motion (a Kamerstuk of the Eerste Kamer), and not'
SELECT EXISTS (
           SELECT 1 FROM edges e
           WHERE e.from_id = d.id AND e.relation = 'ABOUT'
             AND e.to_collection = 'documents'
       ) AS about_the_motion,
       count(*)
FROM decisions d
WHERE lg_str(d.props -> 'kind') = 'Motie' AND lg_str(d.props -> 'chamber') = 'EK'
GROUP BY 1 ORDER BY 1;

\echo '== EK votes that decided a bill (bill_decision), and those on a motion marked so (none)'
SELECT lg_str(props -> 'kind') = 'Motie' AS on_a_motion,
       count(*) FILTER (WHERE (props ->> 'bill_decision')::boolean) AS decided_a_bill,
       count(*) AS votes
FROM decisions
WHERE lg_str(props -> 'chamber') = 'EK' AND starts_with(key, 'ek_')
GROUP BY 1 ORDER BY 1;

\echo '== dossiers with an outcome of the Eerste Kamer, per outcome'
SELECT props -> 'ek_outcome' ->> 'outcome' AS outcome, count(*)
FROM dossiers
WHERE coalesce(json_typeof(props -> 'ek_outcome'), 'null') <> 'null'
GROUP BY 1 ORDER BY 1;
