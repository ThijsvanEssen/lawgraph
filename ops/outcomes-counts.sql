-- How motions, amendments and judgments ended: how many have an outcome, per outcome. Read only, from the light tables
-- (never the text); run before and after `semantic tk-paper-outcomes` and the pass of `normalize rechtspraak` over all
-- (ops/renormalize-judgments.sh), and after `normalize echr`.
--
-- 1. motions and amendments per outcome (lg_document_light).
-- 2. judgments per source and outcome, and conclusions per proposal (lg_judgment_light).
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. motions and amendments per outcome'
SELECT split_part(lg_str(l.props -> 'kind'), ' ', 1) AS kind, lg_str(l.props -> 'outcome') AS outcome, count(*)
FROM lg_document_light l
WHERE starts_with(lg_str(l.props -> 'kind'), 'Motie') OR starts_with(lg_str(l.props -> 'kind'), 'Amendement')
GROUP BY 1, 2 ORDER BY 1, 3 DESC;

\echo '== 2. judgments per source and outcome, conclusions per proposal'
SELECT lg_str(l.props -> 'source') AS source, lg_str(l.props -> 'outcome') AS outcome,
       lg_str(l.props -> 'conclusion_outcome') AS conclusion_outcome, count(*)
FROM lg_judgment_light l
GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;
