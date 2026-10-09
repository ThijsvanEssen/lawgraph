-- #378 check (read-only): REVISES edges from documents.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
SELECT count(*) FROM edges WHERE relation = 'REVISES' AND from_collection = 'documents';
