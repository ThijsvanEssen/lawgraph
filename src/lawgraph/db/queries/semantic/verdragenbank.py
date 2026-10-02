"""The reads of the semantic phase for the Verdragenbank: what the register of each treaty
names (its Tractatenbladen, the dossiers of its approval, the treaties it belongs to)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.db.counting import Store

_TREATY_REGISTERS_SQL = f"""
SELECT key, props -> 'tractatenblad' AS tractatenblad,
       props -> 'kamerstukken' AS kamerstukken,
       props -> 'parent_treaties' AS parent_treaties
FROM {COLLECTION_INSTRUMENTS}
WHERE key LIKE 'verdrag\\_%%'
ORDER BY key
"""


def treaty_registers(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, tractatenblad, kamerstukken, parent_treaties}`` of every Verdragenbank treaty
    (``verdrag_<id>``), by key; the lists are null before its item XML was read."""
    return store.query(_TREATY_REGISTERS_SQL)
