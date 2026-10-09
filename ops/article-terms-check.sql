-- #377 check (read-only): the side tables of semantic graph-article-terms, and the terms of art. 41 Sr.
SET default_transaction_read_only = on;
SET statement_timeout = '120s';
SELECT count(*) AS articles, pg_size_pretty(pg_total_relation_size('lg_article_terms')) AS terms_size,
       (SELECT count(*) FROM lg_summary_stems) AS stems,
       pg_size_pretty(pg_total_relation_size('lg_summary_stems')) AS stems_size
FROM lg_article_terms;
SELECT terms FROM lg_article_terms WHERE article_id = 'articles/bwbr0001854_41';
