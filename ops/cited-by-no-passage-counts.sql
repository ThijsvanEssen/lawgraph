-- The edges of lg_cited_by without a passage, by ECHR and origin: what /articles/.../cited-by lists as a row without a
-- paragraph. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '1800s';
\pset pager off

SELECT c.court_code = 'ECHR' AS echr, e.doc -> 'meta' ->> 'origin' AS origin, count(*)
FROM lg_cited_by c JOIN edges e ON e.key = c.edge_key
WHERE c.mentions = 0 GROUP BY 1, 2 ORDER BY 3 DESC;
