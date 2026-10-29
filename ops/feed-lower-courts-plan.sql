-- The lower courts per day and area of law (/api/feed/summary?lower_courts=true, B14) over
-- 31 days (2026-09-29 to 2026-10-29), read only: the plan and time of the query as the API
-- runs it, then the judgments per lower tier and how many have no area of law.
SET default_transaction_read_only = on;
SET statement_timeout = '60s';
\pset pager off

\echo '== 1. the count, as the API runs it'
EXPLAIN (ANALYZE, BUFFERS)
WITH
    faction_of AS MATERIALIZED (
        SELECT DISTINCT ON (u.fid) u.fid, f.key, CASE WHEN lg_truthy(f.props -> 'abbreviation') THEN f.props -> 'abbreviation' ELSE f.props -> 'name' END AS short
        FROM factions f
        CROSS JOIN LATERAL unnest(
            coalesce(lg_text_array(CASE WHEN lg_truthy(f.props -> 'external_ids') THEN f.props -> 'external_ids' ELSE '[]'::json END), '{}')
            || ARRAY[lg_str(f.props -> 'external_id')]
        ) AS u(fid)
        WHERE u.fid IS NOT NULL
        ORDER BY u.fid, f.key ASC
    ),
    faction_map AS MATERIALIZED (
        -- a lookup only: its keys in no order (``jsonb``)
        SELECT jsonb_object_agg(fid, key) AS map FROM faction_of
    ),
    cabinet_starts AS MATERIALIZED (
        SELECT c.key, lg_str(c.props -> 'from_date') AS from_date
        FROM cabinets c
        WHERE lg_str(c.props -> 'from_date') IS NOT NULL
    ),
    cabinet_periods AS MATERIALIZED (
        SELECT key, from_date, lead(from_date) OVER (ORDER BY from_date) AS until
        FROM (
            SELECT DISTINCT ON (from_date) key, from_date FROM cabinet_starts
            ORDER BY from_date, key DESC
        ) firsts
    ),
    events AS ((
        SELECT ('uitspraak')::text AS kind,
            (9)::int AS rank,
            (n.id)::text AS id,
            (n.published_on)::text AS date,
            (lg_str(CASE WHEN json_typeof(l.labels) = 'array' THEN l.labels -> 0 END))::text AS dossier,
            (NULL)::text AS ministry,
            ('{}'::text[])::text[] AS factions,
            (NULL)::text AS chamber,
            (NULL)::text AS subkind,
            (NULL)::boolean AS passed,
            (NULL)::float8 AS margin,
            ('{}'::text[])::text[] AS coalition
        FROM judgments n
        CROSS JOIN LATERAL (SELECT '[]'::json AS labels OFFSET 0) l
        CROSS JOIN LATERAL (SELECT '[]'::json AS persons OFFSET 0) p
        WHERE (n.published_on >= '2026-09-29') AND (n.published_on <= '2026-10-29') AND (n.stub IS NOT TRUE AND n.same_as IS NULL AND ((n.tier = 'gerechtshof') OR (n.tier = 'rechtbank') OR (n.tier = 'kantongerecht') OR (n.tier = 'tuchtcollege') OR (n.tier = 'andere_instantie') OR (n.tier = 'koninkrijksinstantie')))
    )
    ),
    matching AS (SELECT id, date FROM events WHERE (kind = ANY(ARRAY['uitspraak']::text[]))),
    per_area AS (
        SELECT m.date, a.area, count(*)::int AS count
        FROM matching m
        JOIN judgments j ON j.id = m.id
        CROSS JOIN LATERAL (SELECT lg_subject_areas(j.subjects) AS v) s
        CROSS JOIN LATERAL unnest(CASE WHEN cardinality(s.v) > 0 THEN s.v
                                       ELSE ARRAY[NULL]::text[] END) AS a(area)
        GROUP BY m.date, a.area
    )
    SELECT d.date, d.total,
           json_agg(json_build_object('value', p.area, 'count', p.count)
                    ORDER BY p.count DESC, p.area ASC NULLS LAST) AS subject_areas
    FROM (SELECT date, count(*)::int AS total FROM matching GROUP BY date) d
    JOIN per_area p ON p.date = d.date
    GROUP BY d.date, d.total;

\echo '== 2. per lower tier: judgments in the window, and those without an area of law'
SELECT tier, count(*) AS judgments,
       count(*) FILTER (WHERE cardinality(lg_subject_areas(subjects)) = 0) AS without_area
FROM judgments
WHERE published_on >= '2026-09-29' AND published_on <= '2026-10-29'
  AND stub IS NOT TRUE AND same_as IS NULL
  AND tier IN ('gerechtshof', 'rechtbank', 'kantongerecht', 'tuchtcollege',
               'andere_instantie', 'koninkrijksinstantie')
GROUP BY tier ORDER BY judgments DESC;
