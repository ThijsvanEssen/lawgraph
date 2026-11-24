-- The two relations of the deadlock of the sitemaps of 23 Nov (B213), read only: the error named them by oid
-- (12090399, 13170275); expected an index of documents and one of decisions (ALTER INDEX … SET of the schema).
-- An oid of a relation made again since then names nothing.
SET default_transaction_read_only = on;
\pset pager off

SELECT c.oid, c.relname, c.relkind, t.relname AS of_table
FROM pg_class c
LEFT JOIN pg_index i ON i.indexrelid = c.oid
LEFT JOIN pg_class t ON t.oid = i.indrelid
WHERE c.oid IN (12090399, 13170275);
