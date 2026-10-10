-- How many articles the warm-up should warm (WARM_ARTICLES, now 20): those whose lid counts and cited-by take more
-- than a second cold, about 1,500 citing edges (6:162 BW: 6.6 s cold for its lid counts, cold-reads-plan.sql). Read only.
--
-- 1. articles by their citations (inbound_citation_count, a column): how many have at least so many.
-- 2. the 80 most cited, by the column, each with its citing edges counted (REFERS_TO into it, from the index of edges)
--    and its rank: where the counts fall under 1,500 is the number to warm.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off

\echo '== 1. articles with at least so many citations'
SELECT count(*) FILTER (WHERE inbound_citation_count >= 3000) AS at_least_3000,
       count(*) FILTER (WHERE inbound_citation_count >= 1500) AS at_least_1500,
       count(*) FILTER (WHERE inbound_citation_count >= 1000) AS at_least_1000,
       count(*) FILTER (WHERE inbound_citation_count >= 500) AS at_least_500
FROM articles
WHERE inbound_citation_count > 0;

\echo '== 2. the 80 most cited articles and their citing edges'
SELECT row_number() OVER (ORDER BY a.inbound_citation_count DESC NULLS LAST, a.key) AS rank,
       a.key, a.inbound_citation_count AS citations,
       (SELECT count(*) FROM edges e WHERE e.to_id = a.id AND e.relation = 'REFERS_TO') AS citing_edges
FROM (
    SELECT id, key, inbound_citation_count FROM articles
    WHERE inbound_citation_count > 0
    ORDER BY inbound_citation_count DESC NULLS LAST, key
    LIMIT 80
) a
ORDER BY rank;
