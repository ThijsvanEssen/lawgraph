-- The day of publication of the Staatsblad AMvBs and the Staatscourant regulations, before and after
-- publication-dates.sh: per source the stored records, those whose meta holds what the SRU says (asked) and a day
-- of publication (`published`), and the documents with a date and the newest of them. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== records: stored, asked, with a day of publication'
SELECT source, kind, count(*) AS stored,
       count(*) FILTER (WHERE (doc -> 'meta')::jsonb ? 'creators') AS asked,
       count(*) FILTER (WHERE (doc -> 'meta' ->> 'published') IS NOT NULL) AS published
FROM raw_sources
WHERE (source, kind) IN (('staatsblad', 'stb-amvb-xml'), ('staatscourant', 'stcrt-regeling-xml'))
GROUP BY source, kind
ORDER BY source;

\echo '== documents: with a date, newest'
SELECT source, count(*) AS documents, count(date) AS dated, max(date) AS newest
FROM documents
WHERE source IN ('staatsblad', 'staatscourant')
GROUP BY source
ORDER BY source;
