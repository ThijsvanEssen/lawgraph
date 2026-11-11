-- B143 (the Verloop of a judgment): what normalize rechtspraak and semantic rechtspraak-appeal fill. Read only; run
-- before and after the pass of ops/b143-fill.sh and after the step that rebuilds the edges (the weekly, or
-- ops/b143-fill-appeal.sh). Judgments by a sample of 2% of the pages (times 50): reading the props of a judgment reads
-- its text. The edges in full, by their index on relation.
--
-- 1. judgments of the Rechtspraak with judgment_metadata.procedures and with judgment_metadata.relation_outcomes.
-- 2. the edges of rechtspraak-appeal-linker per relation, and those with meta.source_outcome.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. judgments with procedures and with relation_outcomes (estimate from a 2% sample)'
SELECT count(*) * 50 AS judgments_estimate,
       count(*) FILTER (WHERE json_typeof(j.props -> 'judgment_metadata' -> 'procedures') = 'array') * 50
         AS with_procedures_estimate,
       count(*) FILTER (WHERE json_typeof(j.props -> 'judgment_metadata' -> 'relation_outcomes') = 'object') * 50
         AS with_relation_outcomes_estimate
FROM judgments j TABLESAMPLE SYSTEM (2) REPEATABLE (0)
WHERE j.source = 'rechtspraak' AND NOT coalesce(j.stub, false);

\echo '== 2. edges APPEAL_OF, CONTINUES and REFERRED_BY, and those with source_outcome'
SELECT e.relation, count(*) AS edges,
       count(*) FILTER (WHERE e.doc -> 'meta' ->> 'source_outcome' IS NOT NULL) AS with_source_outcome,
       max(e.created_at) AS latest
FROM edges e
WHERE e.relation IN ('APPEAL_OF', 'CONTINUES', 'REFERRED_BY') AND e.source = 'rechtspraak-appeal-linker'
GROUP BY 1 ORDER BY 1;
