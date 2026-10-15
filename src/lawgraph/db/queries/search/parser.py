"""The parser of typed citations over the laws in the graph: whether a query is an article,
an ECLI or the name of a law (``core.notation``)."""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.aliases import code_aliases, curated_abbreviations
from lawgraph.core.notation import Notation, NotationParser
from lawgraph.db import GraphStore
from lawgraph.db.queries.instrument_names import code_alias_rows
from lawgraph.db.store import read_budget
from lawgraph.db.version_cache import STALE_WAIT, cached


def load_code_aliases(store: GraphStore) -> dict[str, str]:
    """Law abbreviation (``Sr``, ``AVG``) → BWB id or CELEX number
    (``core.aliases.code_aliases``), kept per data version."""
    return cached(
        store,
        ("code-aliases",),
        lambda: code_aliases(code_alias_rows(store), curated_abbreviations()),
        tables=(COLLECTION_INSTRUMENTS,),
    )


def _load_law_names(store: GraphStore) -> dict[str, list[str]]:
    """Lower-case law name → the BWB or CELEX ids that carry it (a name may be shared); the
    ids of one name are listed in one order every time."""
    rows = store.query(
        """
        SELECT coalesce(bwb_id, celex) AS law_id,
               json_build_array(
                   props -> 'short_title', props -> 'citation_title', props -> 'title'
               ) AS names
        FROM instruments
        WHERE coalesce(bwb_id, celex) IS NOT NULL
        ORDER BY law_id, key
        """
    )
    names: dict[str, list[str]] = {}
    for row in rows:
        for name in row["names"]:
            if isinstance(name, str) and name.strip():
                known = names.setdefault(name.strip().lower(), [])
                if row["law_id"] not in known:
                    known.append(row["law_id"])
    return names


def load_notation_parser(store: GraphStore) -> NotationParser:
    """The parser of typed citations over the laws in the graph, kept per data version:
    it reads every instrument (134,000 on the full graph), once for every search and
    resolve until the data changes, and once while many ask (``version_cache``)."""
    return cached(
        store,
        ("notation-parser",),
        # the aliases computed here, not through ``load_code_aliases``: a computation of
        # the cache does not wait for another one (they share a pool)
        lambda: NotationParser(
            code_aliases(code_alias_rows(store), curated_abbreviations()),
            _load_law_names(store),
        ),
        tables=(COLLECTION_INSTRUMENTS,),
    )


def kept_notation_parser(store: GraphStore, wait: float) -> NotationParser | None:
    """The parser of citations, waited for *wait* seconds at most (or what the request has
    left): None when none is kept yet and it is not computed by then (after a start, before
    the warm-up computed it, behind the slow computations of the pool). A search then goes
    on without it, the query taken as words, instead of waiting."""
    with read_budget(wait, "The parser of citations (searched as words)"):
        return load_notation_parser(store)
    return None


def notation(
    store: GraphStore, q: str, types: list[str], wait: float = STALE_WAIT
) -> Notation | None:
    """The citation *q* is, when articles or judgments are searched; None also when the
    parser is not there within *wait* seconds (``kept_notation_parser``)."""
    if not {"articles", "judgments"} & set(types):
        return None
    parser = kept_notation_parser(store, wait)
    return parser.parse(q) if parser else None
