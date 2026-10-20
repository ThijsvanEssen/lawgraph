-- What the run of drops-0.79.65.sh drops and is still there: members.active with the rows that fill it (none), and
-- the indexes on it. Nothing after the run.
SET default_transaction_read_only = on;
SELECT c.table_name || '.' || c.column_name AS column_left, c.data_type,
       (xpath('/row/filled/text()',
              query_to_xml('SELECT count(active) AS filled FROM members', false, true, '')))[1]::text::bigint
           AS filled
FROM information_schema.columns c
WHERE c.table_schema = 'public' AND c.table_name = 'members' AND c.column_name = 'active';
SELECT i.indexrelid::regclass AS index_left
FROM pg_index i
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attname = 'active' AND NOT a.attisdropped
WHERE i.indrelid = 'public.members'::regclass
  AND (a.attnum = ANY(i.indkey::int2[]) OR pg_get_indexdef(i.indexrelid) ~ '\mactive\M')
ORDER BY 1;
