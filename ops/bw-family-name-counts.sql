-- The judgments that cite the Burgerlijk Wetboek by its full name with the book in the number ("artikel 7:669 van het
-- Burgerlijk Wetboek"), which made no edge before the extractor read the name of a family; and whether the loose
-- judgments of RBZWB 2026 were linked at all. Read only; run before and after the relink (ops/relink-judgments.sh).
-- A judgment's text is its props.text, else the text of its props.paragraphs.
--
-- 1. of the judgments of the Rechtspraak, from a sample of 2% of the pages (times 50: an estimate): how many cite that
--    form, and how many of them are loose (no edge either way).
-- 2. the loose judgments of RBZWB 2026, each in one class, the first that holds:
--      family name   cites "N:M ... Burgerlijk Wetboek" (made no edge before the fix)
--      BW code       cites "N:M ... BW", a form the linker has always read: such a judgment was never linked
--                    (it came after the relink, and no nightly ran semantic rechtspraak since)
--      other         neither
--    Before the relink "BW code" says whether the RBZWB judgments missed the linker; after it, "family name" and
--    "BW code" should be (nearly) gone.
SET default_transaction_read_only = on;
SET statement_timeout = '600s';
\pset pager off

\set text 'coalesce(lg_str(j.props -> ''text''), (SELECT string_agg(p ->> ''text'', E''\\n'') FROM json_array_elements(CASE WHEN json_typeof(j.props -> ''paragraphs'') = ''array'' THEN j.props -> ''paragraphs'' ELSE ''[]''::json END) p))'
\set family_name '''\\m\\d{1,2}[a-zA-Z]?:\\d+[a-z]*\\M[^.;\\n]{0,60}?\\mBurgerlijk Wetboek\\M(?!\\s+Boek)'''
\set bw_code '''\\m\\d{1,2}[a-zA-Z]?:\\d+[a-z]*\\M[^.;\\n]{0,60}?\\mBW\\M'''
\set loose 'NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = j.id) AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = j.id)'

\echo '== 1. judgments citing "N:M ... Burgerlijk Wetboek" (estimate from a 2% sample)'
SELECT count(*) * 50 AS judgments_estimate,
       count(*) FILTER (WHERE :loose) * 50 AS loose_estimate
FROM judgments j TABLESAMPLE SYSTEM (2) REPEATABLE (0)
WHERE j.source = 'rechtspraak' AND NOT coalesce(j.stub, false) AND :text ~ :family_name;

\echo '== 2. loose judgments of RBZWB 2026 by class'
SELECT CASE WHEN t ~ :family_name THEN '1 family name' WHEN t ~ :bw_code THEN '2 BW code' ELSE '3 other' END AS class,
       count(*) AS judgments, min(ecli) AS a_sample
FROM (SELECT j.ecli, :text AS t
      FROM judgments j
      WHERE j.source = 'rechtspraak' AND j.court_code = 'RBZWB' AND j.date_eff >= '2026' AND :loose) s
GROUP BY 1 ORDER BY 1;
