-- Staatscourant: what the graph holds of the ministeriele regelingen per day, against the SRU list of 14-28 Oct 2026, read only.
-- A raw record per regeling (retrieve), a document per regeling (normalize), and the instruments of kind publicatie
-- the feed shows as 'publicatie' (only those the BWB names in an article version). dt.modified>=2026-10-14 lists 38 ids.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== A. raw records of the source, per day stored (fetched_at), last 21 days'
SELECT substr(fetched_at, 1, 10) AS day_stored, count(*) AS raw_records
FROM raw_sources WHERE source = 'staatscourant' AND kind = 'stcrt-regeling-xml' AND fetched_at >= '2026-10-08'
GROUP BY 1 ORDER BY 1;

\echo '== B. documents of the source, per publication date (props.date), last 21 days'
SELECT props ->> 'date' AS published, count(*) AS documents, min(props ->> 'identifier') AS first_id, max(props ->> 'identifier') AS last_id
FROM documents WHERE 'Staatscourant' = ANY(labels) AND props ->> 'date' >= '2026-10-08'
GROUP BY 1 ORDER BY 1;

\echo '== C. instruments of kind publicatie from the Staatscourant (the feed "publicatie"), per date_published'
SELECT date_published, count(*) AS publications
FROM instruments
WHERE kind = 'publicatie' AND lg_str(props -> 'publication_kind') = 'Stcrt' AND date_published >= '2026-10-08'
GROUP BY 1 ORDER BY 1;

\echo '== D. the SRU ids against raw records and documents (missing = no raw record)'
WITH sru(id) AS (VALUES
    ('stcrt-2026-33510'),
    ('stcrt-2026-35446'),
    ('stcrt-2026-35717'),
    ('stcrt-2026-35739'),
    ('stcrt-2026-35749'),
    ('stcrt-2026-35819'),
    ('stcrt-2026-36005'),
    ('stcrt-2026-36050'),
    ('stcrt-2026-36242'),
    ('stcrt-2026-36287'),
    ('stcrt-2026-36290'),
    ('stcrt-2026-36294'),
    ('stcrt-2026-36303'),
    ('stcrt-2026-36305'),
    ('stcrt-2026-36369'),
    ('stcrt-2026-36393'),
    ('stcrt-2026-36395'),
    ('stcrt-2026-36411'),
    ('stcrt-2026-36414'),
    ('stcrt-2026-36443'),
    ('stcrt-2026-36518'),
    ('stcrt-2026-36523'),
    ('stcrt-2026-36653'),
    ('stcrt-2026-36802'),
    ('stcrt-2026-36832'),
    ('stcrt-2026-36834'),
    ('stcrt-2026-36858'),
    ('stcrt-2026-36871'),
    ('stcrt-2026-36882'),
    ('stcrt-2026-36884'),
    ('stcrt-2026-36886'),
    ('stcrt-2026-36890'),
    ('stcrt-2026-36935'),
    ('stcrt-2026-16973'),
    ('stcrt-2026-37119'),
    ('stcrt-2026-37215'),
    ('stcrt-2026-37487'),
    ('stcrt-2026-38132')
)
SELECT count(*) AS sru_ids,
       count(r.key) AS in_raw,
       count(d.id) AS in_documents,
       count(*) FILTER (WHERE r.key IS NULL) AS missing_raw,
       string_agg(sru.id, ' ' ORDER BY sru.id) FILTER (WHERE r.key IS NULL) AS missing_ids
FROM sru
LEFT JOIN LATERAL (SELECT key FROM raw_sources WHERE source = 'staatscourant' AND kind = 'stcrt-regeling-xml' AND external_id = sru.id LIMIT 1) r ON true
LEFT JOIN LATERAL (SELECT id FROM documents WHERE 'Staatscourant' = ANY(labels) AND props ->> 'identifier' = sru.id LIMIT 1) d ON true;

\echo '== E. totals'
SELECT (SELECT count(*) FROM raw_sources WHERE source = 'staatscourant' AND kind = 'stcrt-regeling-xml') AS raw_total,
       (SELECT count(*) FROM documents WHERE 'Staatscourant' = ANY(labels)) AS documents_total,
       (SELECT max(props ->> 'date') FROM documents WHERE 'Staatscourant' = ANY(labels)) AS newest_document,
       (SELECT max(fetched_at) FROM raw_sources WHERE source = 'staatscourant') AS newest_fetch;
