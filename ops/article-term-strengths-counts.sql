-- What the step 0 of the strengths of the terms (article-term-strengths.sh) adds: the column
-- lg_article_terms.strengths, nullable; none before the run. And how many articles have terms (the step
-- leaves them).
SET default_transaction_read_only = on;
SELECT table_name || '.' || column_name AS column_there, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'lg_article_terms' AND column_name = 'strengths'
ORDER BY 1;
SELECT count(*) AS articles_with_terms FROM lg_article_terms;
