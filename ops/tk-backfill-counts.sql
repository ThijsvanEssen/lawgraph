-- Read only: where the backfill of the XML of the Tweede Kamer papers stands: the stored XML (records, characters
-- before the gzip of the payload store) and the answers "not at the repository", per year of the paper's date, and the
-- Documents of the graph with a dossier and a number in it (the papers `retrieve tk-content` asks for).
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== stored XML'
SELECT kind, count(*) AS records, sum(payload_chars) AS chars, max(fetched_at) AS last_fetch
FROM raw_sources
WHERE source = 'tk' AND kind IN ('tk-kamerstuk-xml', 'tk-kamerstuk-xml-missing')
GROUP BY kind
ORDER BY kind;

\echo '== papers in a dossier, per year'
SELECT left(lg_str(props -> 'date'), 4) AS year, count(*) AS papers
FROM documents
WHERE 'TK' = ANY(labels)
  AND lg_truthy(props -> 'dossier_number') AND lg_truthy(props -> 'sequence')
GROUP BY 1
ORDER BY 1 DESC NULLS LAST;
