-- Read only: the citations between judgments (REFERS_TO judgment -> judgment), and how many keep the numbers of
-- the paragraphs that name them (meta.paragraphs, #419), which the run over all in relink-citations.sh fills.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off
SELECT count(*) AS citations,
       count(*) FILTER (WHERE json_typeof(doc -> 'meta' -> 'paragraphs') = 'array') AS with_paragraphs
FROM edges
WHERE relation = 'REFERS_TO' AND from_collection = 'judgments' AND to_collection = 'judgments';
