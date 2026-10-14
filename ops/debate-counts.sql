-- Read only: what the debate release (pakket G) writes and reads on prod. The motions that
-- `semantic tk-dossier-relations` makes MADE_IN their debate (how many, and the time of the
-- query); the letters whose text `semantic tk-cited-papers` reads, and the letters without
-- text (`retrieve tk-content` fetches no letter by default); the size of `activities`, which
-- gets the index `activities_number`. Run outside the nightly.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

-- 1. The MADE_IN motion -> debate semantic tk-dossier-relations would write, and how long
--    the query takes (rows and time; the rule is _MOTIONS_SUBMITTED_SQL in
--    db/queries/semantic/tk.py).
EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY ON)
SELECT DISTINCT p.from_id AS paper, a.id AS activity
FROM activities a
JOIN edges ab ON ab.from_id = a.id AND ab.relation = 'ABOUT'
    AND ab.to_collection = 'cases'
JOIN cases c ON c.id = ab.to_id
JOIN edges p ON p.to_id = c.id AND p.relation = 'PART_OF'
    AND p.from_collection = 'documents'
JOIN lg_document_light l ON l.id = p.from_id
WHERE starts_with(coalesce(lg_str(c.props -> 'kind'), ''), 'Motie')
  AND starts_with(coalesce(lg_str(l.props -> 'kind'), ''), 'Motie')
  AND lg_str(a.props -> 'status') = 'Uitgevoerd'
  AND a.date = lg_str(c.props -> 'started_on')
  AND NOT EXISTS (
      SELECT 1
      FROM edges m
      JOIN edges d ON d.from_id = m.from_id
          AND d.relation = 'ABOUT' AND d.to_id = c.id
      WHERE m.to_id = a.id AND m.relation = 'MADE_IN'
        AND m.from_collection = 'decisions'
  )
ORDER BY paper NULLS LAST, activity NULLS LAST;

-- 2. The motions of the wetgevingsoverleg 2026A01323 (expected: 11, 36765-12 and
--    36764-15 to 24).
WITH m AS (
SELECT DISTINCT p.from_id AS paper, a.id AS activity
FROM activities a
JOIN edges ab ON ab.from_id = a.id AND ab.relation = 'ABOUT'
    AND ab.to_collection = 'cases'
JOIN cases c ON c.id = ab.to_id
JOIN edges p ON p.to_id = c.id AND p.relation = 'PART_OF'
    AND p.from_collection = 'documents'
JOIN lg_document_light l ON l.id = p.from_id
WHERE starts_with(coalesce(lg_str(c.props -> 'kind'), ''), 'Motie')
  AND starts_with(coalesce(lg_str(l.props -> 'kind'), ''), 'Motie')
  AND lg_str(a.props -> 'status') = 'Uitgevoerd'
  AND a.date = lg_str(c.props -> 'started_on')
  AND NOT EXISTS (
      SELECT 1
      FROM edges m
      JOIN edges d ON d.from_id = m.from_id
          AND d.relation = 'ABOUT' AND d.to_id = c.id
      WHERE m.to_id = a.id AND m.relation = 'MADE_IN'
        AND m.from_collection = 'decisions'
  )
)
SELECT lg_str(l.props -> 'dossier_number') AS dossier, lg_num(l.props -> 'sequence') AS nr
FROM m JOIN activities a ON a.id = m.activity JOIN lg_document_light l ON l.id = m.paper
WHERE lg_str(a.props -> 'number') = '2026A01323'
ORDER BY 1, 2;

-- 3. The letters of the government whose text semantic tk-cited-papers reads (a full run):
--    how many, and their text in MB; and the letters numbered in a dossier without text, which
--    `retrieve tk-content --kind "brief regering"` would fetch.
SELECT count(*) AS brieven,
       round(sum(length(d.props ->> 'text')) / 1e6, 1) AS tekst_mb
FROM documents d
WHERE d.kind = 'Brief regering' AND d.props ->> 'text' ILIKE '%motie%';
SELECT count(*) AS brieven_zonder_tekst,
       count(*) FILTER (WHERE d.date >= '2024-01-01') AS sinds_2024
FROM documents d
WHERE d.kind = 'Brief regering' AND d.dossier_number IS NOT NULL
  AND lg_num(d.props -> 'sequence') > 0
  AND coalesce(json_typeof(d.props -> 'text'), 'null') <> 'string';

-- 4. Letter 36764 nr. 33: its text and footnotes, and its XML record (the API: no text).
SELECT d.id, lg_str(d.props -> 'text_source') AS bron,
       length(d.props ->> 'text') AS tekst, json_array_length(d.props -> 'footnotes') AS noten
FROM documents d WHERE d.id = 'documents/c673b1db_e3d5_4121_8c12_6566a807ced4';
SELECT key, fetched_at FROM raw_sources
WHERE source = 'tk' AND kind LIKE 'tk-kamerstuk-xml%' AND external_id = 'kst-36764-33';

-- 5. The size of activities (the index activities_number, built at the start).
SELECT count(*) AS activiteiten, pg_size_pretty(pg_total_relation_size('activities')) AS grootte
FROM activities;
