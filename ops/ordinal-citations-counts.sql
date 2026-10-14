-- Read only: an estimate of the article citations whose lid is an ordinal the extractor did not read before
-- B183: "elfde" to "twintigste" ("artikel 5, elfde lid, Awb") and an ordinal in digits after the article
-- ("artikel 36e, 2e lid", "2de lid", "1ste lid"). Such a citation was lost whole or kept without its lid.
-- A sample of 10% of the judgments and the papers (TABLESAMPLE SYSTEM), so the reads stay inside the time-out;
-- the estimate is ten times the count. `semantic rechtspraak` (ops/relink-judgments.sh) and `semantic tk`
-- read them again.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off
WITH texts AS (
  SELECT 'judgments' AS collection, props ->> 'text' AS text FROM judgments TABLESAMPLE SYSTEM (10) REPEATABLE (183)
  UNION ALL
  SELECT 'documents', props ->> 'text' FROM documents TABLESAMPLE SYSTEM (10) REPEATABLE (183)
)
SELECT collection,
       count(*) AS sampled,
       count(*) FILTER (WHERE text ~* '\m(elfde|twaalfde|dertiende|veertiende|vijftiende|zestiende|zeventiende|achttiende|negentiende|twintigste)(\s*(,|en|of)\s*\w+)*\s+lid')
         AS with_eleventh_or_higher,
       count(*) FILTER (WHERE text ~* '\mart(ikel|\.)?\s+\d[0-9a-z.:]*,\s*\d+(e|de|ste)\s+lid')
         AS with_digit_ordinal,
       sum((SELECT count(*) FROM regexp_matches(text, '\m(elfde|twaalfde|dertiende|veertiende|vijftiende|zestiende|zeventiende|achttiende|negentiende|twintigste)\s+lid', 'gi')))
         AS eleventh_or_higher_mentions
FROM texts
WHERE text IS NOT NULL
GROUP BY collection
ORDER BY collection;
