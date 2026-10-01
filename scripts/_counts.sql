-- What a dump holds, one line each, for scripts/backup.sh to write next to a dump and
-- scripts/restore-test.sh to compare a restore with (both sort the lines): the rows of every
-- table, the edges per relation, and the shape of the schema (the columns of every table,
-- the indexes, the functions). Run by psql -A -t: one value per line.
SELECT format('rows %s %s', c.relname,
              (xpath('/row/n/text()',
                     query_to_xml(format('SELECT count(*) AS n FROM %I', c.relname),
                                  false, true, '')))[1]::text)
FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
WHERE s.nspname = 'public' AND c.relkind = 'r';

SELECT format('edges %s %s', coalesce(relation, '-'), count(*)) FROM edges GROUP BY relation;

SELECT format('columns %s %s', table_name, string_agg(column_name, ',' ORDER BY ordinal_position))
FROM information_schema.columns WHERE table_schema = 'public' GROUP BY table_name;

SELECT format('index %s', indexname) FROM pg_indexes WHERE schemaname = 'public';

SELECT format('function %s', p.proname)
FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace
WHERE s.nspname = 'public' AND p.prokind = 'f';
