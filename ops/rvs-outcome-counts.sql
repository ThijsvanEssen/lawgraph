-- The outcome of the judgments of the Raad van State (court RVS): how many have one, per outcome. Read only; run before
-- and after the pass of `normalize rechtspraak` over all (ops/renormalize-rvs.sh).
--
-- 1. RvS judgments per outcome (lg_judgment_light), with the share of those without one.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. RvS judgments per outcome'
SELECT lg_str(l.props -> 'outcome') AS outcome, count(*) AS judgments,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percent
FROM lg_judgment_light l
JOIN judgments j ON j.id = l.id
WHERE j.source = 'rechtspraak' AND j.court_code = 'RVS' AND NOT coalesce(j.stub, false)
GROUP BY 1 ORDER BY 2 DESC;
