-- The pages of the members of the Eerste Kamer and their periods, before and after: the pages stored, the members with
-- periods, the pages of no member (former members of the Eerste Kamer who never sat in the Tweede Kamer: not shown),
-- and the periods of a faction not in the graph. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\echo '== pages, members with periods, pages of no member'
SELECT (SELECT count(*) FROM raw_sources WHERE source = 'eerstekamer' AND kind = 'ek-person-html') AS pages,
       (SELECT count(*) FROM members m
        WHERE json_typeof(m.props -> 'ek_faction_memberships') = 'array') AS members_with_periods,
       (SELECT count(*) FROM raw_sources WHERE source = 'eerstekamer' AND kind = 'ek-person-html')
       - (SELECT count(*) FROM members m
          WHERE json_typeof(m.props -> 'ek_faction_memberships') = 'array') AS pages_of_no_member;

\echo '== periods, and those of a faction not in the graph'
SELECT count(*) AS periods,
       count(*) FILTER (WHERE p ->> 'faction_id' IS NULL) AS without_faction,
       count(*) FILTER (WHERE p ->> 'to_date' IS NULL) AS open
FROM members m, json_array_elements(
    CASE WHEN json_typeof(m.props -> 'ek_faction_memberships') = 'array'
         THEN m.props -> 'ek_faction_memberships' ELSE '[]'::json END) AS p;
