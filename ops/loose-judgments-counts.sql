-- Why judgments of the Rechtspraak are loose (no edge either way), per court and year. Read only. A judgment's text is
-- its props.text, else the text of its props.paragraphs: both on the node (the payload store holds only the raw XML).
--
-- 1. per court and year (at least 200 judgments, a loose share of 15% or more): the share loose and the stubs among
--    them. Reads the columns and the edges' indexes only (edges_from_cover, edges_to_cover), no text.
-- 2. for CRvB 2011-2013 and RBZWB 2026 only (their texts are read): each loose judgment in one class, the first that
--    holds:
--      stub                    a stub (no document of its own)
--      no text                 no text, or under 200 characters
--      law not in graph        the article linker kept unresolved_citations: it read a law the graph lacks
--      LJN only                names an LJN ("LJN BK9271"), which the judgment linker does not read (ECLIs only)
--      article not resolved    names an article ("artikel 8:69 Awb", "art. 7:658 BW") that made no edge: a known law
--                              whose article is missing, or a form the parser does not read (an abbreviation, "die wet")
--      no citation seen        none of these
-- 3. of all judgments of CRvB 2011-2013 (not only loose): how many name an LJN, and how many name an ECLI.
-- 4. samples: per class, five ECLIs of CRvB 2011-2013 and RBZWB 2026 with what a reader sees (the first matches).
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\echo '== 1. loose per court and year (>= 200 judgments, >= 15% loose)'
WITH a AS (
    SELECT j.court_code, left(j.date_eff, 4) AS y, coalesce(j.stub, false) AS stub,
           NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id)
           AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = j.id) AS loose
    FROM judgments j
    WHERE j.source = 'rechtspraak')
SELECT court_code, y, count(*) AS judgments, count(*) FILTER (WHERE loose) AS loose,
       count(*) FILTER (WHERE loose AND stub) AS loose_stubs,
       round(100.0 * count(*) FILTER (WHERE loose) / count(*), 1) AS pct
FROM a
GROUP BY 1, 2
HAVING count(*) >= 200 AND count(*) FILTER (WHERE loose) >= 0.15 * count(*)
ORDER BY pct DESC
LIMIT 40;

\set loose 'WITH loose AS (SELECT j.ecli, j.court_code, left(j.date_eff, 4) AS y, coalesce(j.stub, false) AS stub, coalesce(lg_str(j.props -> ''text''), (SELECT string_agg(p ->> ''text'', E''\\n'') FROM json_array_elements(CASE WHEN json_typeof(j.props -> ''paragraphs'') = ''array'' THEN j.props -> ''paragraphs'' ELSE ''[]''::json END) p)) AS t, j.props -> ''unresolved_citations'' AS unresolved FROM judgments j WHERE j.source = ''rechtspraak'' AND ((j.court_code = ''CRVB'' AND j.date_eff >= ''2011'' AND j.date_eff < ''2014'') OR (j.court_code = ''RBZWB'' AND j.date_eff >= ''2026'')) AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id) AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = j.id)), c AS (SELECT *, CASE WHEN stub THEN ''1 stub'' WHEN coalesce(length(t), 0) < 200 THEN ''2 no text'' WHEN json_typeof(unresolved) = ''array'' THEN ''3 law not in graph'' WHEN t ~ ''LJN[: ]*[A-Z]{2}\\s?\\d{4}'' THEN ''4 LJN only'' WHEN t ~* ''\\m(artikel|art\\.)\\s+\\d'' THEN ''5 article not resolved'' ELSE ''6 no citation seen'' END AS why FROM loose)'

\echo '== 2. why loose: CRvB 2011-2013 and RBZWB 2026'
:loose
SELECT court_code, y, why, count(*) AS judgments
FROM c GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo '== 3. CRvB 2011-2013, all judgments: naming an LJN, naming an ECLI'
SELECT y, count(*) AS judgments,
       count(*) FILTER (WHERE t ~ 'LJN[: ]*[A-Z]{2}\s?\d{4}') AS name_an_ljn,
       count(*) FILTER (WHERE t ~* 'ECLI:NL:') AS name_an_ecli,
       count(*) FILTER (WHERE t IS NULL) AS without_text
FROM (SELECT left(j.date_eff, 4) AS y,
             coalesce(lg_str(j.props -> 'text'), (SELECT string_agg(p ->> 'text', E'\n') FROM json_array_elements(
                 CASE WHEN json_typeof(j.props -> 'paragraphs') = 'array' THEN j.props -> 'paragraphs' ELSE '[]'::json END) p)) AS t
      FROM judgments j
      WHERE j.source = 'rechtspraak' AND j.court_code = 'CRVB' AND j.date_eff >= '2011' AND j.date_eff < '2014') s
GROUP BY 1 ORDER BY 1;

\echo '== 4. samples (5 per court and class) with what a reader sees'
:loose
SELECT court_code, why, ecli,
       (regexp_match(t, '(LJN[: ]*[A-Z]{2}\s?\d{4})'))[1] AS ljn,
       (regexp_match(t, '((?:[Aa]rtikel|art\.)\s+\d[^\n.;]{0,50})'))[1] AS article,
       left((SELECT string_agg(u ->> 'raw_match', ' | ') FROM json_array_elements(
           CASE WHEN json_typeof(unresolved) = 'array' THEN unresolved ELSE '[]'::json END) u), 120) AS law_not_in_graph
FROM (SELECT c.*, row_number() OVER (PARTITION BY court_code, why ORDER BY ecli) AS n FROM c) s
WHERE n <= 5
ORDER BY court_code, why, ecli;

\echo '== 5. the laws not in the graph the loose judgments of CRvB 2011-2013 and RBZWB 2026 cite (top 25)'
:loose
SELECT court_code, u ->> 'law' AS law, count(*) AS citations, count(DISTINCT ecli) AS judgments
FROM c, json_array_elements(CASE WHEN json_typeof(unresolved) = 'array' THEN unresolved ELSE '[]'::json END) u
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 25;
