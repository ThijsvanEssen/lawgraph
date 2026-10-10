-- The faction votes a member is given while they held a post in a cabinet: per cabinet, the members whose seat in a
-- faction of the Tweede Kamer (faction_memberships) overlaps a post (government_functions), how many days, how many
-- of those overlaps are still open on both sides (a seat without an end beside a post held now: no seat end in the
-- source), and how many faction votes (lg_faction_votes) fall in the overlap and so reach the member's page. A
-- demissionary minister may sit in the Kamer (Grondwet art. 57), so an overlap is not wrong in itself; one that runs
-- into a cabinet the member was not demissionary in is. Then the 30 overlaps with the most votes. Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\set overlaps 'WITH o AS (SELECT m.key, m.props ->> ''name'' AS name, g ->> ''cabinet'' AS cabinet, g ->> ''function'' AS post, p ->> ''faction_id'' AS faction_id, p ->> ''faction_key'' AS faction, greatest(p ->> ''from_date'', g ->> ''from_date'') AS from_d, least(coalesce(p ->> ''to_date'', ''9999-12-31''), coalesce(g ->> ''to_date'', ''9999-12-31'')) AS to_d, p ->> ''to_date'' IS NULL AND g ->> ''to_date'' IS NULL AS both_open FROM members m CROSS JOIN LATERAL json_array_elements(CASE WHEN json_typeof(m.pj_faction_memberships) = ''array'' THEN m.pj_faction_memberships ELSE ''[]''::json END) p CROSS JOIN LATERAL json_array_elements(CASE WHEN json_typeof(m.props -> ''government_functions'') = ''array'' THEN m.props -> ''government_functions'' ELSE ''[]''::json END) g WHERE m.in_parliament AND g ->> ''from_date'' IS NOT NULL AND p ->> ''from_date'' IS NOT NULL), ov AS (SELECT *, (SELECT count(*) FROM lg_faction_votes v WHERE v.faction_id = o.faction_id AND v.date >= o.from_d AND v.date <= o.to_d) AS votes FROM o WHERE o.from_d <= o.to_d)'

\echo '== per cabinet: members with a seat beside a post, overlaps still open, faction votes in the overlaps'
:overlaps
SELECT cabinet, count(DISTINCT key) AS members, count(*) FILTER (WHERE both_open) AS open_both,
       sum(least(to_d, to_char(current_date, 'YYYY-MM-DD'))::date - from_d::date + 1) AS overlap_days,
       sum(votes) AS faction_votes
FROM ov GROUP BY 1 ORDER BY min(from_d) DESC;

\echo '== the 30 overlaps with the most faction votes'
:overlaps
SELECT name, cabinet, post, faction, from_d, to_d, both_open, votes
FROM ov ORDER BY votes DESC, from_d DESC LIMIT 30;
