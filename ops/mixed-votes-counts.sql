-- Read-only: decisions taken for a roll call (vote_kind member) that hold far fewer member votes than a roll
-- call of the Tweede Kamer (150): a faction vote with a few members voting apart, whose faction rows were
-- dropped (core/tk_records.decision: roll_call = any row with a Persoon_Id).
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
SELECT CASE WHEN n < 10 THEN '1-9' WHEN n < 100 THEN '10-99' ELSE '100+' END AS member_votes,
       count(*) AS decisions, min(date) AS first, max(date) AS last
FROM (
    SELECT d.date, (SELECT count(*) FROM edges e WHERE e.to_id = d.id AND e.relation = 'VOTED') AS n
    FROM decisions d
    WHERE lg_str(d.props -> 'vote_kind') = 'member' AND 'TK' = ANY(d.labels)
) x
GROUP BY 1
ORDER BY 1;
