-- What the step 0 of the laws of the Staatsblad (official-id.sh) adds: the column articles.official_id and the
-- index articles_official_id_article_number, valid; none before the run.
SET default_transaction_read_only = on;
SELECT table_name || '.' || column_name AS column_there, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'articles' AND column_name = 'official_id'
ORDER BY 1;
SELECT indexrelid::regclass AS index_there, indisvalid AS valid
FROM pg_index
WHERE indexrelid::regclass::text = 'articles_official_id_article_number'
ORDER BY 1;
