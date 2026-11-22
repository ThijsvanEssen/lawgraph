"""The vocabulary a search that found nothing suggests from (``core.suggestions``): the names
of the concepts and the words of the titles of the laws and the dossiers, kept per data
version of those two tables."""

from __future__ import annotations

import re
from collections import Counter

from lawgraph.config.constants import COLLECTION_DOSSIERS, COLLECTION_INSTRUMENTS
from lawgraph.core.concepts import concept_names
from lawgraph.core.suggestions import Vocabulary, vocabulary
from lawgraph.db import GraphStore
from lawgraph.db.version_cache import cached

# The titles (folded, as the search columns hold them: ``s_<field>_g``) of the laws, the
# publications of the Staatsblad and Staatscourant left out, and of the dossiers.
_TITLES = """
SELECT coalesce(s_citation_title_g, '') || ' ' || coalesce(s_title_g, '')
FROM instruments WHERE kind IS DISTINCT FROM 'publicatie'
UNION ALL
SELECT coalesce(s_title_g, '') FROM dossiers
"""
_WORD = re.compile(r"[^\W_]+")


def _title_words(store: GraphStore) -> Counter[str]:
    """Each word of the titles (``_TITLES``) with the number of titles that hold it; no
    number."""
    found: Counter[str] = Counter()
    for title in store.query(_TITLES):
        found.update({w for w in _WORD.findall(title) if not w.isdigit()})
    return found


def load_suggestion_words(store: GraphStore) -> Vocabulary:
    """The names of the concepts (``core.concepts.concept_names``) and the words of the
    titles of the laws and the dossiers, as ``core.suggestions.vocabulary`` keeps them."""
    return cached(
        store,
        ("suggestion-words",),
        lambda: vocabulary(
            ((name, c.term) for name, c in concept_names().values()),
            _title_words(store),
        ),
        tables=(COLLECTION_INSTRUMENTS, COLLECTION_DOSSIERS),
    )
