-- What the step 0 of 0.79.60 (drops-0.79.60.sh) drops and is still there: none of it after the run.
SET default_transaction_read_only = on;
SELECT table_name || '.' || column_name AS column_left
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (column_name = 'search_tsv' OR (table_name = 'dossiers' AND column_name IN ('sort_order', 'closed_on')))
ORDER BY 1;
SELECT indexrelid::regclass AS index_left, indrelid::regclass AS on_table
FROM pg_index
WHERE indrelid::regclass::text IN ('articles', 'instruments', 'judgments', 'dossiers', 'documents', 'committees')
  AND pg_get_indexdef(indexrelid) ~ '\m(search_tsv|sort_order|closed_on)\M'
ORDER BY 1;
SELECT p.oid::regprocedure AS function_left
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname IN ('lg_tsv', 'lg_bm25')
ORDER BY 1;
SELECT t AS table_left
FROM unnest(ARRAY['lg_led_state', 'lg_faction_votes_state', 'lg_authored_state', 'lg_authored_dated']) t
WHERE to_regclass('public.' || t) IS NOT NULL
ORDER BY 1;
