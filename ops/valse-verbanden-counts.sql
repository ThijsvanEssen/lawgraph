-- What the deploy of "valse verbanden" (pakket E) will remove, counted before it: upper bounds. Read only.
-- 1. REFERS_TO of semantic tk (source tk-article-linker) to a whole instrument: a run that no longer reads the
--    record of a paper (props.raw) removes those its title, text and footnotes do not make; an article citation
--    from the record alone is rare. Those whose snippet holds a GUID or a TK document number came from the record.
-- 2. AMENDS / INTRODUCES / REPEALS from a paper to the act its own dossier made (LEGISLATED_IN) or to an article
--    of that act: exactly what tk-amends and tk-amendment-articles remove.
-- 3. The Tweede Kamer papers, for the time of a full semantic tk.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. REFERS_TO of semantic tk, per target collection and reason; with a GUID or document number in the snippet'
SELECT e.to_collection,
       lg_str(e.doc -> 'meta' -> 'reason') AS reason,
       count(*) AS edges,
       count(*) FILTER (
           WHERE lg_str(e.doc -> 'meta' -> 'snippet')
                 ~ '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\m20[0-9]{2}D[0-9]{5}\M'
       ) AS snippet_from_record
FROM edges e
WHERE e.relation = 'REFERS_TO' AND e.source = 'tk-article-linker'
GROUP BY 1, 2
ORDER BY 1, 2;

\echo '== 2. changes from a paper to the act of its own dossier, or to an article of it, per source and relation'
SELECT e.source, e.relation, e.to_collection, count(DISTINCT e.key) AS edges, count(DISTINCT e.from_id) AS papers
FROM edges l
JOIN dossiers ds ON ds.id = l.to_id AND ds.label IS NOT NULL
JOIN instruments act ON act.id = l.from_id
JOIN documents d ON d.dossier_numbers @> ARRAY[ds.label]
JOIN edges e ON e.from_id = d.id
WHERE l.relation = 'LEGISLATED_IN' AND l.to_collection = 'dossiers'
  AND e.relation IN ('AMENDS', 'INTRODUCES', 'REPEALS')
  AND e.source IN ('tk-amends-instrument', 'amendment-article-linker')
  AND (e.to_id = act.id OR EXISTS (
      SELECT 1 FROM articles a WHERE a.id = e.to_id AND a.bwb_id = lg_str(act.props -> 'bwb_id')))
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

\echo '== 2b. the same for dossier 36764 (Cyberbeveiligingswet)'
SELECT e.source, e.relation, count(*) AS edges, count(DISTINCT e.from_id) AS papers
FROM documents d
JOIN edges e ON e.from_id = d.id
WHERE d.dossier_numbers @> ARRAY['36764']
  AND e.relation IN ('AMENDS', 'INTRODUCES', 'REPEALS')
  AND (e.to_id = 'instruments/bwbr0052872'
       OR EXISTS (SELECT 1 FROM articles a WHERE a.id = e.to_id AND a.bwb_id = 'BWBR0052872'))
GROUP BY 1, 2
ORDER BY 1, 2;

\echo '== 2c. REFERS_TO of semantic tk from the papers of dossier 36764, per target'
SELECT e.to_id, count(*) AS papers
FROM documents d
JOIN edges e ON e.from_id = d.id
WHERE d.dossier_numbers @> ARRAY['36764']
  AND e.relation = 'REFERS_TO' AND e.source = 'tk-article-linker' AND e.to_collection = 'instruments'
GROUP BY 1
ORDER BY 2 DESC, 1;

\echo '== 3. Tweede Kamer papers'
SELECT count(*) AS papers FROM documents d WHERE 'TK' = ANY(d.labels);
