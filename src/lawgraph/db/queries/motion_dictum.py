"""The motions and amendments of the Tweede Kamer whose dictum or explanation ``semantic
tk-dictum`` keeps (``core/motion_dictum.py``, ``core/amendment_explanation.py``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.tk_records.kinds import KIND_AMENDMENT, KIND_MOTION
from lawgraph.db.counting import Store

# The papers of one statement: their text is read (a few kilobytes each).
BATCH = 2_000

# The motions (``Motie``, ``Motie (gewijzigd/nader)``) and amendments (``Amendement``,
# ``Amendement (gewijzigd/nader/vervangend)``) with text after *after*, those without a dictum
# (a motion) or an explanation (an amendment) yet unless *every*; by their index of the kind.
_PAPERS = f"""
SELECT d.id, d.key, starts_with(d.kind, '{KIND_MOTION}') AS motion,
       lg_str(d.props -> 'text') AS text,
       CASE WHEN starts_with(d.kind, '{KIND_AMENDMENT}') THEN d.props -> 'sections' END
           AS sections
FROM {COLLECTION_DOCUMENTS} d
WHERE (starts_with(d.kind, '{KIND_MOTION}') OR starts_with(d.kind, '{KIND_AMENDMENT}'))
  AND d.id > %(after)s
  AND coalesce(json_typeof(d.props -> 'text'), 'null') = 'string'
  AND (%(every)s OR coalesce(json_typeof(d.props -> CASE
          WHEN starts_with(d.kind, '{KIND_MOTION}') THEN 'dictum' ELSE 'explanation' END),
       'null') = 'null')
ORDER BY d.id
LIMIT %(batch)s
"""


def papers_with_text(store: Store, after: str, every: bool) -> list[dict[str, Any]]:
    """``{id, key, motion, text, sections}`` of the next ``BATCH`` motions and amendments
    with text after the id *after* (``sections`` of an amendment only)."""
    return list(store.query(_PAPERS, {"after": after, "every": every, "batch": BATCH}))
