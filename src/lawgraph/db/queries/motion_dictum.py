"""The motions of the Tweede Kamer whose dictum ``semantic tk-dictum`` keeps
(``core/motion_dictum.py``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.db.counting import Store

# The motions of one statement: their text is read (a few kilobytes each).
BATCH = 2_000

# The motions (``Motie``, ``Motie (gewijzigd/nader)``) with text after *after*, those without
# a dictum yet unless *every*; by their index of the kind.
_MOTIONS = f"""
SELECT d.id, d.key, lg_str(d.props -> 'text') AS text
FROM {COLLECTION_DOCUMENTS} d
WHERE starts_with(d.kind, 'Motie') AND d.id > %(after)s
  AND coalesce(json_typeof(d.props -> 'text'), 'null') = 'string'
  AND (%(every)s OR coalesce(json_typeof(d.props -> 'dictum'), 'null') = 'null')
ORDER BY d.id
LIMIT %(batch)s
"""


def motions_with_text(store: Store, after: str, every: bool) -> list[dict[str, Any]]:
    """``{id, key, text}`` of the next ``BATCH`` motions with text after the id *after*."""
    return list(store.query(_MOTIONS, {"after": after, "every": every, "batch": BATCH}))
