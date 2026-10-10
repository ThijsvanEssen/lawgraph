-- The members without any edge (no seat, vote, signature, post or committee in the graph): who they are, by where
-- their node comes from and when they were born, and whether the member list, the search and the sitemap show them.
-- Read only; the members table is small (its props are read).
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== members by source, those without edges, and where they show'
WITH m AS (
    SELECT m.key, m.list_name, m.in_parliament, m.in_ek,
           coalesce(cardinality(m.cabinet_keys), 0) > 0 AS in_cabinet,
           lg_str(m.props -> 'external_id') IS NOT NULL AS tk_person,
           left(lg_str(m.props -> 'birth_date'), 4) AS born,
           lg_str(m.props -> 'slug') IS NOT NULL AS slugged,
           NOT EXISTS (SELECT 1 FROM edges e WHERE e.from_id = m.id)
           AND NOT EXISTS (SELECT 1 FROM edges e WHERE e.to_id = m.id) AS alone
    FROM members m
)
SELECT CASE WHEN key LIKE 'ek\_%' THEN 'EK only (ek_)'
            WHEN in_parliament THEN 'TK with seat periods'
            WHEN in_cabinet THEN 'cabinet post, no seat'
            WHEN in_ek THEN 'EK seen, no TK seat'
            WHEN tk_person THEN 'TK Persoon, no seat in the data'
            ELSE 'other' END AS source,
       count(*) AS members,
       count(*) FILTER (WHERE alone) AS without_edges,
       count(*) FILTER (WHERE alone AND list_name <> '') AS alone_named_found_by_search,
       count(*) FILTER (WHERE alone AND in_parliament) AS alone_in_member_list,
       count(*) FILTER (WHERE alone AND slugged) AS alone_with_a_page,
       count(*) FILTER (WHERE alone AND born < '1900') AS alone_born_before_1900,
       count(*) FILTER (WHERE alone AND born >= '1900' AND born < '1940') AS alone_born_1900_1939,
       count(*) FILTER (WHERE alone AND born >= '1940') AS alone_born_1940_on,
       count(*) FILTER (WHERE alone AND born IS NULL) AS alone_born_unknown
FROM m
GROUP BY ROLLUP (1)
ORDER BY 1 ASC NULLS LAST;
