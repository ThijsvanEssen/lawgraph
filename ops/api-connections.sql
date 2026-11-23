-- The connections of the API and the pipelines (application_name lawgraph-<pid>; the API is the process with
-- the most) as they are now, read only, short statements too: per connection its state, what it waits for and
-- how long, then ten samples a second apart of how many wait for what (DataFileRead: a read from disk).
SET default_transaction_read_only = on;
\pset pager off

-- 1. every connection, the longest in its state first
SELECT application_name, pid,
       state,
       wait_event_type, wait_event,
       round(extract(epoch FROM now() - state_change)::numeric, 1) AS in_state_s,
       round(extract(epoch FROM now() - query_start)::numeric, 1) AS query_s,
       round(extract(epoch FROM now() - xact_start)::numeric, 1) AS xact_s,
       left(regexp_replace(query, '\s+', ' ', 'g'), 100) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND application_name LIKE 'lawgraph-%' AND pid <> pg_backend_pid()
ORDER BY application_name, state_change;

-- 2. per process, state and wait: how many, ten times a second apart
SELECT now()::time(0) AS at, application_name, state, coalesce(wait_event, '-') AS wait_event, count(*) AS n,
       round(max(extract(epoch FROM now() - query_start))::numeric, 1) AS longest_s
FROM pg_stat_activity
WHERE datname = current_database() AND application_name LIKE 'lawgraph-%' AND pid <> pg_backend_pid()
GROUP BY application_name, state, wait_event
ORDER BY application_name, n DESC
\watch i=1 c=10
