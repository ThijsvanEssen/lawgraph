-- The counter of each table the API serves (lg_data_version), read only: run before and after a poll, the tables
-- whose counter moved are the ones it wrote, and the warm-up computes again only the parts that read them.
SET default_transaction_read_only = on;
\pset pager off

SELECT now()::time(0) AS at, collection, version FROM lg_data_version ORDER BY collection;
