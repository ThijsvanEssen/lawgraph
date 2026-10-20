-- Practice terms (wanprestatie, ontslag op staande voet, ...) and the article each means: why the
-- article search does not name that article (a term of strength `NAMED`, 0.15, for every word of the
-- query). Read only; 27 articles and two controls (noodweer, art. 41 Sr, named; bestemmingsplan, art.
-- 3:2 Awb, not named), their citing judgments' light summaries, the terms table, and the snippets of
-- the citations (a 10% sample of the pages of `edges` for the rates over all citations).
--
-- 1. per article: its citations, its terms with their strength (lg_article_terms), and the strength
--    of each stem of the practice term (- not a term).
-- 2. per stem: the articles that have it as a term and those it names (strength >= 0.15), and the
--    article's place among them by citations (the search takes the first 1000, TERMED).
-- 3. per article and stem, as `semantic graph-article-terms` weighs it: of its citing judgments how
--    many have the stem in their light summary, the share of its citers and of the summaries that
--    hold the stem, the lift, the strength (the lower bound of the share of holders, NAME_LIFT 50),
--    and its place among the article's candidate terms (at most 20 kept, the heaviest first).
-- 4. the definitions (lg_instrument_definitions) of BW Boek 3, 6, 7 and the Awb whose term is a
--    practice term.
-- 5. the same stem in the snippets of the citations (`meta.mentions[].snippet` of the REFERS_TO edge,
--    the r.o. around the cited article): of the article's citing judgments how many have it there,
--    against how many of all citing judgments (the sample) have it in the snippet of any citation.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\set targets 'WITH t(term, article_id) AS (VALUES (''wanprestatie'', ''articles/bwbr0005289_74''), (''onrechtmatige daad'', ''articles/bwbr0005289_162''), (''ingebrekestelling'', ''articles/bwbr0005289_82''), (''dwaling'', ''articles/bwbr0005289_228''), (''ongerechtvaardigde verrijking'', ''articles/bwbr0005289_212''), (''onverschuldigde betaling'', ''articles/bwbr0005289_203''), (''eigen schuld'', ''articles/bwbr0005289_101''), (''verjaring'', ''articles/bwbr0005291_310''), (''bedrog'', ''articles/bwbr0005291_44''), (''redelijkheid en billijkheid'', ''articles/bwbr0005289_248''), (''opschortingsrecht'', ''articles/bwbr0005289_52''), (''ontbinding'', ''articles/bwbr0005289_265''), (''ontslag op staande voet'', ''articles/bwbr0005290_677''), (''dringende reden'', ''articles/bwbr0005290_678''), (''transitievergoeding'', ''articles/bwbr0005290_673''), (''billijke vergoeding'', ''articles/bwbr0005290_681''), (''concurrentiebeding'', ''articles/bwbr0005290_653''), (''werkgeversaansprakelijkheid'', ''articles/bwbr0005290_658''), (''loondoorbetaling bij ziekte'', ''articles/bwbr0005290_629''), (''proeftijd'', ''articles/bwbr0005290_652''), (''bezwaartermijn'', ''articles/bwbr0005537_6_7''), (''motiveringsbeginsel'', ''articles/bwbr0005537_3_46''), (''zorgvuldigheidsbeginsel'', ''articles/bwbr0005537_3_2''), (''evenredigheidsbeginsel'', ''articles/bwbr0005537_3_4''), (''belanghebbende'', ''articles/bwbr0005537_1_2''), (''last onder dwangsom'', ''articles/bwbr0005537_5_32''), (''verzuimherstel'', ''articles/bwbr0005537_6_6''), (''noodweer'', ''articles/bwbr0001854_41''), (''bestemmingsplan'', ''articles/bwbr0005537_3_2'')), ts AS (SELECT t.term, t.article_id, s.stem FROM t CROSS JOIN LATERAL unnest(lg_tokens(t.term)) AS s(stem)), cites AS (SELECT DISTINCT t.article_id, e.from_id AS judgment_id FROM (SELECT DISTINCT article_id FROM t) t JOIN edges e ON e.to_id = t.article_id AND e.relation = ''REFERS_TO'' AND e.from_collection = ''judgments''), citers AS (SELECT article_id, count(*) AS n FROM cites GROUP BY 1), total AS (SELECT judgments::numeric AS n FROM lg_summary_stems WHERE stem = '''')'

\echo '== 0. light summaries: rows (the total of lg_summary_stems) and those with a summary'
SELECT (SELECT judgments FROM lg_summary_stems WHERE stem = '') AS counted,
       count(*) AS light, count(*) FILTER (WHERE lg_str(props -> 'summary') <> '') AS with_summary
FROM lg_judgment_light;

\echo '== 1. per article: citations, terms with their strength, the stems of the practice term'
:targets
SELECT t.term, t.article_id, a.inbound_citation_count AS cited, c.n AS citers,
       (SELECT string_agg(u.term || ':' || u.strength, ' ' ORDER BY u.o)
        FROM unnest(at.terms, at.strengths) WITH ORDINALITY AS u(term, strength, o)) AS terms,
       (SELECT string_agg(s.stem || ':' || coalesce((SELECT u.strength::text FROM unnest(at.terms, at.strengths) AS u(term, strength) WHERE u.term = s.stem), '-'), ' ')
        FROM ts s WHERE s.article_id = t.article_id AND s.term = t.term) AS stems
FROM t
LEFT JOIN articles a ON a.id = t.article_id
LEFT JOIN citers c ON c.article_id = t.article_id
LEFT JOIN lg_article_terms at ON at.article_id = t.article_id
ORDER BY t.term;

\echo '== 2. per stem: articles that have it as a term, those it names, the article by citations'
:targets
SELECT s.term, s.stem, x.with_term, x.named, x.place, x.held, x.strength
FROM ts s
CROSS JOIN LATERAL (
    SELECT count(*) AS with_term,
           count(*) FILTER (WHERE k.strength >= 0.15) AS named,
           min(k.place) FILTER (WHERE k.article_id = s.article_id) AS place,
           bool_or(k.article_id = s.article_id) AS held,
           max(k.strength) FILTER (WHERE k.article_id = s.article_id) AS strength
    FROM (
        SELECT a.article_id, u.strength,
               row_number() OVER (ORDER BY r.inbound_citation_count DESC NULLS LAST, r.key) AS place
        FROM lg_article_terms a
        JOIN articles r ON r.id = a.article_id
        CROSS JOIN LATERAL unnest(a.terms, a.strengths) AS u(term, strength)
        WHERE a.terms @> ARRAY[s.stem] AND u.term = s.stem
    ) k
) x
ORDER BY s.term, s.stem;

\echo '== 3. per article and stem: as graph-article-terms weighs it (rank: among its candidate terms)'
:targets
, stems AS (
    SELECT c.article_id, x.stem, count(*) AS n
    FROM cites c
    JOIN lg_judgment_light l ON l.id = c.judgment_id
    CROSS JOIN LATERAL (SELECT DISTINCT u AS stem FROM unnest(lg_tokens(lg_str(l.props -> 'summary'))) AS u) x
    GROUP BY 1, 2
), scored AS (
    SELECT s.article_id, s.stem, s.n, c.n AS citers, greatest(w.judgments, s.n) AS holders,
           (s.n::numeric / c.n) / (greatest(w.judgments, s.n) / (SELECT n FROM total)) AS lift,
           s.n >= 3 AND (s.n >= 0.2 * c.n OR s.n >= 0.2 * w.judgments) AS candidate
    FROM stems s JOIN citers c ON c.article_id = s.article_id
    LEFT JOIN lg_summary_stems w ON w.stem = s.stem
), ranked AS (
    SELECT *, CASE WHEN candidate AND lift >= 5 AND length(stem) >= 3 AND stem !~ '^[0-9]+$'
                   THEN rank() OVER (PARTITION BY article_id, candidate AND lift >= 5 AND length(stem) >= 3 AND stem !~ '^[0-9]+$'
                                     ORDER BY weight DESC) END AS place
    FROM (SELECT *, n * ln(least(lift, 1e6)) AS weight FROM scored) z
)
SELECT s.term, s.stem, c.n AS citers, coalesce(r.n, 0) AS with_stem,
       round(coalesce(r.n, 0)::numeric / c.n, 3) AS share_citers, r.holders,
       round(r.n::numeric / r.holders, 3) AS share_holders, round(r.lift, 1) AS lift,
       -- the lower bound of the Wilson interval (95 %) of the share of holders (wilson_lower)
       CASE WHEN r.lift >= 50 THEN round((r.n::numeric / r.holders + 3.8416 / (2 * r.holders)
            - 1.96 * sqrt((r.n::numeric / r.holders) * (1 - r.n::numeric / r.holders) / r.holders
                          + 3.8416 / (4.0 * r.holders * r.holders)))
            / (1 + 3.8416 / r.holders), 3) END AS strength, r.place,
       (SELECT round(max(q.weight), 1) FROM ranked q WHERE q.article_id = s.article_id AND q.place = 20) AS weight_20th,
       round(r.weight, 1) AS weight
FROM ts s
LEFT JOIN citers c ON c.article_id = s.article_id
LEFT JOIN ranked r ON r.article_id = s.article_id AND r.stem = s.stem
ORDER BY s.term, s.stem;

\echo '== 4. definitions of BW 3, 6, 7 and the Awb whose term is a practice term'
:targets
SELECT d.bwb_id, x ->> 'term' AS term, x ->> 'jci' AS jci, x -> 'scope' ->> 'path' AS scope_path,
       left(x ->> 'text', 80) AS text
FROM lg_instrument_definitions d
CROSS JOIN LATERAL json_array_elements(d.definitions) AS x
WHERE d.bwb_id IN ('BWBR0005291', 'BWBR0005289', 'BWBR0005290', 'BWBR0005537')
  AND lower(x ->> 'term') IN (SELECT term FROM t)
ORDER BY 1, 2;

\echo '== 5. per article and stem: in the snippets of its citations, against all citations (10% sample)'
:targets
, sample AS MATERIALIZED (
    SELECT e.from_id AS judgment_id, lg_tokens(m ->> 'snippet') AS stems
    FROM edges e TABLESAMPLE SYSTEM (10) REPEATABLE (1)
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array' THEN e.doc -> 'meta' -> 'mentions' ELSE '[]' END) m
    WHERE e.relation = 'REFERS_TO' AND e.from_collection = 'judgments' AND e.to_collection = 'articles'
), base AS (
    SELECT s.stem, count(DISTINCT x.judgment_id) AS judgments
    FROM (SELECT DISTINCT stem FROM ts) s
    JOIN sample x ON x.stems @> ARRAY[s.stem]
    GROUP BY 1
), everyone AS (SELECT count(DISTINCT judgment_id) AS judgments FROM sample),
near AS (
    SELECT s.term, s.stem, e.from_id AS judgment_id,
           bool_or(lg_tokens(m ->> 'snippet') @> ARRAY[s.stem]) AS held
    FROM ts s
    JOIN edges e ON e.to_id = s.article_id AND e.relation = 'REFERS_TO' AND e.from_collection = 'judgments'
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(e.doc -> 'meta' -> 'mentions') = 'array' THEN e.doc -> 'meta' -> 'mentions' ELSE '[]' END) m
    GROUP BY 1, 2, 3
)
SELECT n.term, n.stem, count(*) AS citers_with_snippet, count(*) FILTER (WHERE n.held) AS with_stem,
       round(count(*) FILTER (WHERE n.held)::numeric / count(*), 3) AS share_citers,
       b.judgments AS sample_with_stem, (SELECT judgments FROM everyone) AS sample_citing,
       round((count(*) FILTER (WHERE n.held)::numeric / count(*))
             / nullif(b.judgments::numeric / (SELECT judgments FROM everyone), 0), 1) AS lift
FROM near n
LEFT JOIN base b ON b.stem = n.stem
GROUP BY n.term, n.stem, b.judgments
ORDER BY 1, 2;
