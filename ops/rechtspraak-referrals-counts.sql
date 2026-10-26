-- The ANSWERS edges of the preliminary rulings (rechtspraak-referral-linker) and the rulings that answer no decision.
-- Read only; run before and after `semantic rechtspraak-referrals` over all (ops/rechtspraak-referrals-steps.sh).
--
-- 1. the ANSWERS edges by basis (formal: props.related_eclis; referral_text: the text names who asked).
-- 2. the preliminary rulings, those with an ANSWERS edge and those without.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. ANSWERS edges of rechtspraak-referral-linker, by basis'
SELECT e.doc -> 'meta' ->> 'basis' AS basis, count(*) AS edges, count(DISTINCT e.from_id) AS rulings,
       max(e.created_at) AS latest
FROM edges e
WHERE e.relation = 'ANSWERS' AND e.source = 'rechtspraak-referral-linker'
GROUP BY 1 ORDER BY 1;

\echo '== 2. preliminary rulings, answered and not'
SELECT count(*) AS rulings,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id AND e.relation = 'ANSWERS'))
         AS answered,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id AND e.relation = 'ANSWERS'))
         AS unanswered
FROM judgments j
WHERE j.procedure = 'Prejudiciële beslissing';
