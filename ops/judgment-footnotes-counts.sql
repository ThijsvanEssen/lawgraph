-- The footnotes of the judgments: how many keep them, and how many article citations come from one. Read only; run
-- before and after `normalize rechtspraak` over all (ops/renormalize-judgments.sh) and the relink after it. Estimates
-- from a sample of 2% of the pages (times 50): reading the props of a judgment reads its text.
--
-- 1. judgments of the Rechtspraak: with footnotes kept (props.footnotes).
-- 2. article citations of judgments (REFERS_TO of the rechtspraak linker): those with a mention in a footnote.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. judgments with footnotes kept (estimate from a 2% sample)'
SELECT count(*) * 50 AS judgments_estimate,
       count(*) FILTER (WHERE json_typeof(j.props -> 'footnotes') = 'array') * 50 AS with_footnotes_estimate
FROM judgments j TABLESAMPLE SYSTEM (2) REPEATABLE (0)
WHERE j.source = 'rechtspraak' AND NOT coalesce(j.stub, false);

\echo '== 2. article citations with a mention in a footnote (estimate from a 2% sample)'
SELECT count(*) * 50 AS citations_estimate,
       count(*) FILTER (WHERE (e.doc -> 'meta' -> 'mentions')::text LIKE '%"footnote"%') * 50 AS from_a_footnote_estimate
FROM edges e TABLESAMPLE SYSTEM (2) REPEATABLE (0)
WHERE e.relation = 'REFERS_TO' AND e.from_collection = 'judgments' AND e.to_collection = 'articles';
