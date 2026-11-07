-- B110 bron 1 before and after: per source the stored publications, those whose meta holds what the SRU says of
-- their creators (the end of `retrieve staatsblad` and `staatscourant`), the papers by who issued them
-- (`ministry_missing`: no_creator, unlinked) and the LED_BY edges from a paper to a ministry. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== records: stored, asked'
SELECT source, kind, count(*) AS stored,
       count(*) FILTER (WHERE (doc -> 'meta')::jsonb ? 'creators') AS asked
FROM raw_sources
WHERE (source, kind) IN (('staatsblad', 'stb-amvb-xml'), ('staatscourant', 'stcrt-regeling-xml'))
GROUP BY source, kind
ORDER BY source;

\echo '== papers: linked, gaps'
SELECT source, count(*) AS papers,
       count(*) FILTER (WHERE json_typeof(props -> 'ministries') = 'array'
                          AND json_array_length(props -> 'ministries') > 0) AS linked,
       count(*) FILTER (WHERE lg_str(props -> 'ministry_missing') = 'no_creator') AS no_creator,
       count(*) FILTER (WHERE lg_str(props -> 'ministry_missing') = 'unlinked') AS unlinked,
       count(*) FILTER (WHERE props -> 'creators' IS NULL) AS not_asked
FROM documents
WHERE source IN ('staatsblad', 'staatscourant')
GROUP BY source
ORDER BY source;

\echo '== creators not linked (top 20)'
SELECT c.creator, count(*) AS papers
FROM documents d, json_array_elements_text(d.props -> 'creators') AS c(creator)
WHERE d.source IN ('staatsblad', 'staatscourant') AND lg_str(d.props -> 'ministry_missing') = 'unlinked'
GROUP BY c.creator
ORDER BY papers DESC, c.creator
LIMIT 20;

\echo '== LED_BY from a paper, per ministry'
SELECT to_id, count(*) AS papers
FROM edges
WHERE relation = 'LED_BY' AND from_collection = 'documents'
GROUP BY to_id
ORDER BY papers DESC, to_id;
