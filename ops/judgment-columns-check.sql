-- Do the stored columns of judgments hold what their props hold? Read only, and it reads the props of every judgment
-- (about 30 min on web-1): by day, not during the nightly. Every count must be 0 before a step reads the column instead.
SET default_transaction_read_only = on;
SET statement_timeout = '3600s';
\pset pager off

\echo '== rows whose column differs from its props'
SELECT count(*) AS judgments,
       count(*) FILTER (WHERE j.ecli IS DISTINCT FROM lg_str(j.props -> 'ecli')) AS ecli,
       count(*) FILTER (WHERE (coalesce(json_typeof(j.props -> 'replaced_by'), 'null') <> 'null') <> (j.replaced_by IS NOT NULL)) AS replaced_by,
       count(*) FILTER (WHERE j.replaced_by IS DISTINCT FROM lg_str(j.props -> 'replaced_by')) AS replaced_by_value,
       count(*) FILTER (WHERE (coalesce(json_typeof(j.props -> 'same_as'), 'null') <> 'null') <> (j.same_as IS NOT NULL)) AS same_as,
       count(*) FILTER (WHERE j.same_as IS DISTINCT FROM lg_str(j.props -> 'same_as')) AS same_as_value,
       count(*) FILTER (WHERE (coalesce(json_typeof(j.props -> 'series_id'), 'null') <> 'null') <> (j.series_id IS NOT NULL)) AS series_id,
       count(*) FILTER (WHERE (j.props -> 'summary')::text IS DISTINCT FROM j.pj_summary::text) AS pj_summary,
       count(*) FILTER (WHERE (j.props -> 'date_eff')::text IS DISTINCT FROM j.pj_date_eff::text) AS pj_date_eff
FROM judgments j;
