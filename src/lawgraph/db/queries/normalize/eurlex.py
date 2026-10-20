"""The graph reads of the normalize phase for EUR-Lex."""

from __future__ import annotations

from psycopg import sql

from lawgraph.config.constants import COLLECTION_ARTICLES, COLLECTION_INSTRUMENTS
from lawgraph.db.counting import Store


def case_law_keys(store: Store, collection: str) -> list[str]:
    """The keys of the instruments or articles (*collection*) of a CELEX number of sector 6:
    case law, which is a judgment and never an act."""
    if collection not in (COLLECTION_INSTRUMENTS, COLLECTION_ARTICLES):
        raise ValueError(f"No CELEX number in {collection!r}")
    statement = sql.SQL(
        "SELECT key FROM {} WHERE starts_with(celex, '6') ORDER BY key"
    ).format(sql.Identifier(collection))
    return [str(key) for key in store.query(statement)]
