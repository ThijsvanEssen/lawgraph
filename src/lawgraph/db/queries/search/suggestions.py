"""The vocabulary a search that found nothing suggests from (``core.suggestions``): the names
of the concepts and the words of the titles of the laws and the dossiers, kept per data
version of those two tables."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_DOSSIERS, COLLECTION_INSTRUMENTS
from lawgraph.core.concepts import concept_names
from lawgraph.core.suggestions import WORD, Vocabulary, vocabulary
from lawgraph.db import GraphStore
from lawgraph.db.version_cache import cached

# Each word of the titles (folded, as the search columns hold them: ``s_<field>_g``) of the
# laws, the publications of the Staatsblad and Staatscourant left out, and of the dossiers,
# with the number of titles that hold it; no number.
_TITLE_WORDS = f"""
SELECT word, count(DISTINCT id)::int AS n
FROM (
    SELECT id, regexp_split_to_table(
        coalesce(s_citation_title_g, '') || ' ' || coalesce(s_title_g, ''), '[^[:alnum:]]+'
    ) AS word
    FROM instruments WHERE kind IS DISTINCT FROM 'publicatie'
    UNION ALL
    SELECT id, regexp_split_to_table(coalesce(s_title_g, ''), '[^[:alnum:]]+')
    FROM dossiers
) titled
WHERE length(word) >= {WORD} AND word !~ '^[0-9]+$'
GROUP BY word
"""


def load_suggestion_words(store: GraphStore) -> Vocabulary:
    """The names of the concepts (``core.concepts.concept_names``) and the words of the
    titles of the laws and the dossiers, as ``core.suggestions.vocabulary`` keeps them."""
    return cached(
        store,
        ("suggestion-words",),
        lambda: vocabulary(
            ((name, c.term) for name, c in concept_names().values()),
            {row["word"]: row["n"] for row in store.query(_TITLE_WORDS)},
        ),
        tables=(COLLECTION_INSTRUMENTS, COLLECTION_DOSSIERS),
    )
