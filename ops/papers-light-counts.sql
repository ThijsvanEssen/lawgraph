-- Read only: the light rows of the papers (lg_document_light), and how many hold has_text, true or false. Before
-- `semantic graph-light --papers` the rows kept before the flag have none; after it every row has it. Reads the
-- light table and the ids of documents only, never a paper's text.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== Papers, their light rows, and has_text'
SELECT (SELECT count(*) FROM documents) AS papers,
       count(*) AS light_rows,
       count(*) FILTER (WHERE json_typeof(l.props -> 'has_text') = 'boolean') AS with_flag,
       count(*) FILTER (WHERE l.props ->> 'has_text' = 'true') AS has_text,
       count(*) FILTER (WHERE l.props ->> 'has_text' = 'false') AS without_text
FROM lg_document_light l;
