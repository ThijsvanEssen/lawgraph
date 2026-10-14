-- Where the citations of the text linkers stand, against what the detail routes serve: the text of a paper
-- (`/api/documents/{key}` serves `title` and `text`, not yet its footnotes) and the paragraphs of a judgment
-- (`/api/judgments/{ecli}` serves `paragraphs`, not yet its footnotes). Read only; run before the deploy that
-- serves the footnotes, and after the renormalize and the relinks that place every citation (meta.place,
-- meta.mentions). Estimates from a sample of PCT% of the pages (default 2: psql -v pct=5 for more); a row of a
-- paper or a judgment reads its props, which is its whole text.
--
-- 1. Kamerstukken, `tk-article-linker`: per kind of paper, where the words of each edge (meta.raw_match) stand:
--    in `text`, in a footnote (`noot`, 2010 on; `voetnoot`, an endnote of the paper before 2010), in the title, or
--    elsewhere (the record of the Tweede Kamer: a dossier title, an actor; or a paper without text). Since the
--    relink: meta.place.part.
-- 2. The same: the cited laws found most often in a footnote alone.
-- 3. The MvT of 33328 (Wet open overheid) and the VIR-BI (BWBR0016435), the case of 14 Oct.
-- 4. Judgments, `rechtspraak-article-linker`: per tier, edges by where their mentions stand (meta.mentions:
--    paragraphs, footnotes, both, or none kept).
-- 5. Judgments, `judgment-citation-linker`: per tier, where the cited ECLI (its number), LJN or application number
--    stands: in a paragraph, in a footnote only, or neither (another part of the XML; or footnotes not kept).
-- 6. What the prod steps read: stored Kamerstuk XML, papers with footnotes (and with markers), edges per linker.
SET default_transaction_read_only = on;
SET statement_timeout = '900s';
\if :{?pct}
\else
\set pct 2
\endif
\pset pager off

\echo '== 1. Kamerstukken: tk-article-linker edges by kind and where the citation stands (estimate)'
WITH d AS (
    SELECT d.id, coalesce(d.kind, '(none)') AS kind,
           d.props ->> 'xml_dialect' AS dialect,
           d.props ->> 'text' AS text,
           d.props ->> 'title' AS title,
           (SELECT string_agg(n ->> 'text', E'\n')
              FROM json_array_elements(CASE WHEN json_typeof(d.props -> 'footnotes') = 'array'
                                            THEN d.props -> 'footnotes' END) n) AS notes
    FROM documents d TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
    WHERE 'TK' = ANY (d.labels)
), placed AS (
    SELECT d.kind,
           CASE
             WHEN e.doc -> 'meta' ->> 'raw_match' IS NULL THEN 'other'
             WHEN strpos(d.text, e.doc -> 'meta' ->> 'raw_match') > 0 THEN 'text'
             WHEN strpos(d.notes, e.doc -> 'meta' ->> 'raw_match') > 0
               THEN CASE WHEN d.dialect = 'kamerwrk' THEN 'endnote' ELSE 'footnote' END
             WHEN strpos(d.title, e.doc -> 'meta' ->> 'raw_match') > 0 THEN 'title'
             ELSE 'other'
           END AS place,
           d.text IS NULL AS no_text
    FROM d
    JOIN edges e ON e.from_id = d.id AND e.relation = 'REFERS_TO'
    WHERE e.source = 'tk-article-linker'
)
SELECT coalesce(kind, '== all') AS kind,
       count(*) * 100 / :pct AS edges,
       count(*) FILTER (WHERE place = 'text') * 100 / :pct AS in_text,
       count(*) FILTER (WHERE place = 'title') * 100 / :pct AS in_title,
       count(*) FILTER (WHERE place = 'footnote') * 100 / :pct AS in_footnote,
       count(*) FILTER (WHERE place = 'endnote') * 100 / :pct AS in_endnote,
       count(*) FILTER (WHERE place = 'other' AND NOT no_text) * 100 / :pct AS other_record,
       count(*) FILTER (WHERE place = 'other' AND no_text) * 100 / :pct AS other_no_text,
       round(100.0 * count(*) FILTER (WHERE place NOT IN ('text', 'title')) / count(*), 1)
         AS pct_not_served
FROM placed
GROUP BY GROUPING SETS ((kind), ())
ORDER BY kind IS NOT NULL, count(*) DESC
LIMIT 31;

\echo '== 2. Kamerstukken: the targets cited most often in a footnote or endnote only (sample counts)'
WITH d AS (
    SELECT d.id, d.props ->> 'text' AS text, d.props ->> 'title' AS title,
           (SELECT string_agg(n ->> 'text', E'\n')
              FROM json_array_elements(CASE WHEN json_typeof(d.props -> 'footnotes') = 'array'
                                            THEN d.props -> 'footnotes' END) n) AS notes
    FROM documents d TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
    WHERE 'TK' = ANY (d.labels)
)
SELECT e.to_id, count(*) AS edges_in_sample,
       min(e.doc -> 'meta' ->> 'raw_match') AS a_raw_match,
       min(d.id) AS a_paper
FROM d
JOIN edges e ON e.from_id = d.id AND e.relation = 'REFERS_TO'
WHERE e.source = 'tk-article-linker'
  AND strpos(d.notes, e.doc -> 'meta' ->> 'raw_match') > 0
  AND coalesce(strpos(d.text, e.doc -> 'meta' ->> 'raw_match'), 0) = 0
  AND coalesce(strpos(d.title, e.doc -> 'meta' ->> 'raw_match'), 0) = 0
GROUP BY e.to_id
ORDER BY count(*) DESC, e.to_id
LIMIT 15;

\echo '== 3. The MvT of 33328 and the VIR-BI'
SELECT e.to_id, e.doc -> 'meta' ->> 'raw_match' AS raw_match,
       strpos(d.props ->> 'text', e.doc -> 'meta' ->> 'raw_match') > 0 AS in_text,
       e.doc -> 'meta' -> 'place' ->> 'part' AS part,
       e.doc -> 'meta' -> 'place' ->> 'footnote_id' AS footnote_id
FROM edges e
JOIN documents d ON d.id = e.from_id
WHERE e.from_id = 'documents/3de9f42e_532f_4e0e_b22a_092dfd4cd0ca' AND e.relation = 'REFERS_TO'
  AND e.to_id LIKE '%bwbr0016435%';

\echo '== 4. Judgments: rechtspraak-article-linker edges by tier and where the mentions stand (estimate)'
WITH m AS (
    SELECT j.tier,
           json_typeof(e.doc -> 'meta' -> 'mentions') = 'array' AS has_mentions,
           (SELECT count(*) FROM json_array_elements(
                CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                     THEN e.doc -> 'meta' -> 'mentions' END) x
             WHERE x ->> 'footnote' IS NOT NULL) AS in_notes,
           (SELECT count(*) FROM json_array_elements(
                CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array'
                     THEN e.doc -> 'meta' -> 'mentions' END) x
             WHERE x ->> 'footnote' IS NULL) AS in_paragraphs
    FROM edges e TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
    JOIN judgments j ON j.id = e.from_id
    WHERE e.relation = 'REFERS_TO' AND e.source = 'rechtspraak-article-linker'
)
SELECT coalesce(tier, '== all') AS tier,
       count(*) * 100 / :pct AS edges,
       count(*) FILTER (WHERE in_paragraphs > 0 AND in_notes = 0) * 100 / :pct AS paragraphs_only,
       count(*) FILTER (WHERE in_paragraphs > 0 AND in_notes > 0) * 100 / :pct AS paragraphs_and_footnotes,
       count(*) FILTER (WHERE in_paragraphs = 0 AND in_notes > 0) * 100 / :pct AS footnotes_only,
       count(*) FILTER (WHERE NOT coalesce(has_mentions, false)) * 100 / :pct AS no_mentions
FROM m
GROUP BY GROUPING SETS ((tier), ())
ORDER BY tier IS NOT NULL, count(*) DESC;

\echo '== 5. Judgments: judgment-citation-linker edges by tier and where the citation stands (estimate)'
WITH j AS (
    SELECT j.id, j.tier,
           json_typeof(j.props -> 'footnotes') = 'array' AS notes_kept,
           (SELECT string_agg(p ->> 'text', E'\n')
              FROM json_array_elements(CASE WHEN json_typeof(j.props -> 'paragraphs') = 'array'
                                            THEN j.props -> 'paragraphs' END) p) AS paragraphs,
           (SELECT string_agg(n ->> 'text', E'\n')
              FROM json_array_elements(CASE WHEN json_typeof(j.props -> 'footnotes') = 'array'
                                            THEN j.props -> 'footnotes' END) n) AS notes
    FROM judgments j TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
    WHERE j.source = 'rechtspraak' AND NOT coalesce(j.stub, false)
), c AS (
    SELECT j.tier, j.notes_kept, j.paragraphs, j.notes,
           json_typeof(e.doc -> 'meta' -> 'mentions') = 'array' AS has_mentions,
           json_typeof(e.doc -> 'meta' -> 'paragraphs') = 'array' AS has_paragraphs,
           CASE
             WHEN e.doc -> 'meta' ->> 'cited_appno' IS NOT NULL THEN e.doc -> 'meta' ->> 'cited_appno'
             WHEN split_part(e.doc -> 'meta' ->> 'cited_ecli', ':', 5) ~ '^[A-Z]{2}[0-9]{4}$'
               THEN split_part(e.doc -> 'meta' ->> 'cited_ecli', ':', 5)
             ELSE split_part(e.doc -> 'meta' ->> 'cited_ecli', ':', 4) || ':'
                  || split_part(e.doc -> 'meta' ->> 'cited_ecli', ':', 5)
           END AS needle
    FROM j
    JOIN edges e ON e.from_id = j.id AND e.relation = 'REFERS_TO' AND e.to_collection = 'judgments'
    WHERE e.source = 'judgment-citation-linker'
), placed AS (
    SELECT tier, has_mentions, has_paragraphs,
           CASE
             WHEN strpos(upper(paragraphs), needle) > 0 THEN 'paragraph'
             WHEN strpos(upper(notes), needle) > 0 THEN 'footnote'
             WHEN NOT coalesce(notes_kept, false) THEN 'other: footnotes not kept'
             ELSE 'other'
           END AS place
    FROM c
)
SELECT coalesce(tier, '== all') AS tier,
       count(*) * 100 / :pct AS edges,
       count(*) FILTER (WHERE place = 'paragraph') * 100 / :pct AS in_paragraph,
       count(*) FILTER (WHERE place = 'footnote') * 100 / :pct AS in_footnote_only,
       count(*) FILTER (WHERE place = 'other: footnotes not kept') * 100 / :pct AS other_notes_not_kept,
       count(*) FILTER (WHERE place = 'other') * 100 / :pct AS other,
       count(*) FILTER (WHERE has_paragraphs) * 100 / :pct AS with_meta_paragraphs,
       count(*) FILTER (WHERE has_mentions) * 100 / :pct AS with_meta_mentions,
       round(100.0 * count(*) FILTER (WHERE place <> 'paragraph') / count(*), 1) AS pct_not_served
FROM placed
GROUP BY GROUPING SETS ((tier), ())
ORDER BY tier IS NOT NULL, count(*) DESC;

\echo '== 6. What the prod steps read'
SELECT count(*) AS kamerstuk_xml_records
FROM raw_sources WHERE source = 'tk' AND kind = 'tk-kamerstuk-xml';
SELECT count(*) * 100 / :pct AS tk_papers_estimate,
       count(*) FILTER (WHERE json_typeof(d.props -> 'text') = 'string') * 100 / :pct AS with_text,
       count(*) FILTER (WHERE json_typeof(d.props -> 'footnotes') = 'array'
                          AND json_array_length(d.props -> 'footnotes') > 0) * 100 / :pct AS with_footnotes,
       count(*) FILTER (WHERE (d.props -> 'footnotes')::text LIKE '%"at"%') * 100 / :pct AS with_markers
FROM documents d TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
WHERE 'TK' = ANY (d.labels);
SELECT e.source, count(*) * 100 / :pct AS edges_estimate,
       count(*) FILTER (WHERE json_typeof(e.doc -> 'meta' -> 'place') = 'object'
                           OR json_typeof(e.doc -> 'meta' -> 'mentions') = 'array') * 100 / :pct AS placed
FROM edges e TABLESAMPLE SYSTEM (:pct) REPEATABLE (0)
WHERE e.relation = 'REFERS_TO'
  AND e.source IN ('tk-article-linker', 'rechtspraak-article-linker', 'judgment-citation-linker')
GROUP BY e.source
ORDER BY e.source;
