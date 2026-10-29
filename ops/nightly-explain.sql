-- Why three Rechtspraak steps of the nightly take 25-35 min for a few rows, read only (EXPLAIN without ANALYZE: nothing runs).
-- A: rechtspraak-duplicates as it reads (props of every judgment) against the stored columns replaced_by / same_as.
-- B: rechtspraak-series likewise (series_id). C: rechtspraak-conclusions (props.judgment_metadata.document_type).
-- D: the size of the tables behind them.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== A1. replaced_judgments as it is'
EXPLAIN SELECT j.id, j.key, j.props -> 'ecli', j.props -> 'replaced_by', j.props -> 'same_as'
FROM judgments j
WHERE coalesce(json_typeof(j.props -> 'replaced_by'), 'null') <> 'null' OR coalesce(json_typeof(j.props -> 'same_as'), 'null') <> 'null'
ORDER BY j.key;

\echo '== A2. the same on the stored columns'
EXPLAIN SELECT j.id, j.key, j.ecli, j.replaced_by, j.same_as
FROM judgments j
WHERE j.replaced_by IS NOT NULL OR j.same_as IS NOT NULL
ORDER BY j.key;

\echo '== B1. judgments_in_series as it is'
EXPLAIN SELECT j.props -> 'ecli' FROM judgments j
WHERE coalesce(json_typeof(j.props -> 'series_id'), 'null') <> 'null' ORDER BY j.key;

\echo '== B2. the same on the stored column'
EXPLAIN SELECT j.ecli FROM judgments j WHERE j.series_id IS NOT NULL ORDER BY j.key;

\echo '== C. conclusion_rows: every judgment of the source, props read for the document type and the named conclusions'
EXPLAIN SELECT j.key, j.props -> 'ecli', j.props -> 'conclusion_eclis'
FROM judgments j
WHERE j.source = 'rechtspraak'
  AND (lg_str(j.props -> 'judgment_metadata' -> 'document_type') IS NOT DISTINCT FROM 'Conclusie'
       OR coalesce(json_array_length(j.props -> 'conclusion_eclis'), 0) > 0);

\echo '== D. sizes'
SELECT relname, reltuples::bigint AS rows, pg_size_pretty(pg_relation_size(oid)) AS heap,
       pg_size_pretty(pg_total_relation_size(oid) - pg_relation_size(oid)) AS toast_and_indexes
FROM pg_class WHERE relname IN ('judgments', 'edges', 'lg_judgment_light', 'lg_cited_by', 'lg_judgment_persons', 'instruments', 'articles') ORDER BY 1;
