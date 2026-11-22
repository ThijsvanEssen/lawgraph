"""What a search that found nothing suggests instead (``/api/search``, ``suggestions``): the
names most like its words by ``pg_trgm`` ``similarity``, a term or variant of the list of
concepts or a name of an act of ``eu-core`` (``core.concepts.concept_names``), or a word of
the titles of the laws and the dossiers that the trigram indexes of their titles find
(``<%``: ``q`` like a part of the title)."""

from __future__ import annotations

from lawgraph.core.concepts import concept_key, concept_names
from lawgraph.db import GraphStore

# The least similarity of a name to the query (``pg_trgm`` has 0.3 by default; at 0.4 a
# typo or another form of a long word is in, a word that only shares a part is out).
SIMILAR = 0.4
# The most suggestions.
MOST = 3
# The titles of each table whose words are compared, the most like the query first.
TITLES = 20
# The fewest characters of a word of a title.
WORD = 4

# The words of the titles of the laws (no publication of the Staatsblad or Staatscourant)
# and the dossiers that hold a part like ``q`` (their trigram indexes), and the names of the
# concepts, compared by their folded ``key``: the most like first, then a concept, then by
# name; more than ``MOST``, as a concept is suggested by one name only.
_SUGGESTIONS = f"""
WITH titles AS (
    (SELECT s_citation_title_g AS title FROM instruments
     WHERE %(q)s <%% s_citation_title_g AND kind IS DISTINCT FROM 'publicatie'
     ORDER BY word_similarity(%(q)s, s_citation_title_g) DESC NULLS LAST LIMIT {TITLES})
    UNION ALL
    (SELECT s_title_g FROM dossiers WHERE %(q)s <%% s_title_g
     ORDER BY word_similarity(%(q)s, s_title_g) DESC NULLS LAST LIMIT {TITLES})
),
named AS (
    SELECT name, key, true AS concept
    FROM unnest(%(names)s::text[], %(keys)s::text[]) AS n(name, key)
    UNION ALL
    SELECT DISTINCT w, w, false
    FROM titles, regexp_split_to_table(title, '[^[:alnum:]]+') AS w
    WHERE length(w) >= {WORD} AND w !~ '^[0-9]+$'
)
SELECT name FROM named
WHERE key <> %(q)s AND similarity(key, %(q)s) >= {SIMILAR}
ORDER BY round(similarity(key, %(q)s)::numeric, 2) DESC NULLS LAST,
    concept DESC NULLS LAST, name NULLS LAST
LIMIT {MOST * 3}
"""


def suggested(store: GraphStore, q: str) -> list[str]:
    """At most ``MOST`` queries to try instead of *q* (its words searched), the most like
    it first (``_SUGGESTIONS``), a concept by one of its names only."""
    key = concept_key(q)
    if not key:
        return []
    names = concept_names()
    rows = store.query(
        _SUGGESTIONS,
        {"q": key, "names": [name for name, _ in names.values()], "keys": list(names)},
    )
    found: dict[str, str] = {}
    for name in rows:
        concept = names.get(concept_key(name))
        found.setdefault(concept[1].term if concept else name, name)
    return list(found.values())[:MOST]
