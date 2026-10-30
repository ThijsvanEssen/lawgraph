-- The Tweede Kamer papers before 2008-2009, which the OData of the Tweede Kamer hardly has: per session year the
-- documents and those numbered in a dossier, whether dossier 25877 (Wiv 2002) is in the graph, the dossiers the Tweede
-- Kamer answered it did not have. Read only; columns and indexes.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== TK documents per session year (up to 2008-2009)'
SELECT coalesce(lg_str(d.props -> 'session_year'), '') AS session_year,
       d.source,
       count(*) AS documents,
       count(*) FILTER (WHERE d.dossier_number IS NOT NULL) AS in_a_dossier
FROM documents d
WHERE 'TK' = ANY (d.labels)
  AND coalesce(lg_str(d.props -> 'session_year'), '') < '2009-2010'
GROUP BY ROLLUP (1, 2)
ORDER BY 1 NULLS LAST, 2 NULLS LAST;

\echo '== Dossier 25877: its node, its documents by source, the raw records that say the Tweede Kamer had none'
SELECT id, type, labels, lg_str(props -> 'source') AS source, lg_str(props -> 'title') AS title
FROM dossiers
WHERE number = '25877';
SELECT source, count(*) AS documents
FROM documents
WHERE dossier_number = '25877' OR '25877' = ANY (dossier_numbers)
GROUP BY source;
SELECT kind, external_id, lg_str(doc -> 'meta' -> 'retry_after') AS retry_after
FROM raw_sources
WHERE source = 'tk' AND kind LIKE '%-missing' AND external_id = '25877';

\echo '== tk-dossier-missing by dossier number: below 31200 is a dossier opened before 2007-2008'
SELECT CASE WHEN external_id ~ '^\d+$' AND external_id::int < 31200 THEN 'before 2007-2008' ELSE 'later' END AS opened,
       count(*) AS missing
FROM raw_sources
WHERE source = 'tk' AND kind = 'tk-dossier-missing'
GROUP BY ROLLUP (1)
ORDER BY 1 NULLS LAST;
