-- How complete the chain of amended amendments is: the amendment papers whose title says they replace another
-- ("Gewijzigd amendement ... ter vervanging van nr. 8"), against those with a REVISES of the rule vervanging (from
-- Zaak.VervangenVanuit, semantic tk-dossier-relations), per year; and ten whose title says so without the edge. The
-- title and the kinds of a paper are read from lg_document_light, never its props (they hold its text). Read only.
SET default_transaction_read_only = on;
SET statement_timeout = '300s';
\pset pager off

\set amendments 'WITH a AS (SELECT l.id, lg_str(l.props -> ''title'') AS title, left(lg_str(l.props -> ''date''), 4) AS y, coalesce(lg_str(l.props -> ''title''), '''') ~* ''ter vervanging van'' AS says, EXISTS (SELECT 1 FROM edges e WHERE e.from_id = l.id AND e.relation = ''REVISES'' AND e.to_collection = ''documents'' AND e.doc -> ''meta'' ->> ''rule'' = ''vervanging'') AS edge FROM lg_document_light l WHERE (l.props -> ''case_kinds'')::text LIKE ''%Amendement%'')'

\echo '== amendment papers, those that say they replace another, those with the edge'
:amendments
SELECT count(*) AS papers,
       count(*) FILTER (WHERE says) AS says_it_replaces,
       count(*) FILTER (WHERE edge) AS with_edge,
       count(*) FILTER (WHERE says AND edge) AS both,
       count(*) FILTER (WHERE says AND NOT edge) AS says_without_edge,
       count(*) FILTER (WHERE edge AND NOT says) AS edge_without_saying
FROM a;

\echo '== per year (since 2008)'
:amendments
SELECT y, count(*) FILTER (WHERE says) AS says_it_replaces, count(*) FILTER (WHERE says AND edge) AS with_edge
FROM a WHERE y >= '2008' GROUP BY y ORDER BY y;

\echo '== ten that say they replace another, without the edge (newest first)'
:amendments
SELECT id, y, left(title, 110) AS title FROM a WHERE says AND NOT edge ORDER BY y DESC NULLS LAST, id LIMIT 10;
