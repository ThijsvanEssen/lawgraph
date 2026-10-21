"""What ``semantic tk-motion-kinds`` reads: the subject of every motion and of every decision
on one, with the kind kept before (``core/motion_kinds.py``)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DECISIONS, COLLECTION_DOCUMENTS
from lawgraph.core.tk_records.kinds import KIND_MOTION
from lawgraph.db.counting import Store

# The motions (``Motie``, ``Motie (gewijzigd/nader)``) dated on or after %(since)s (every one
# without it): the title of a motion is its own ``Onderwerp``
# (``core/tk_records/documents.document_title``), read with the kind kept before from its
# light row, never its props (its text).
_DOCUMENTS = f"""
SELECT d.id, d.key, lg_str(l.props -> 'title') AS subject,
       lg_str(l.props -> 'motion_kind') AS kept
FROM {COLLECTION_DOCUMENTS} d
JOIN lg_document_light l ON l.id = d.id
WHERE starts_with(d.kind, '{KIND_MOTION}')
  AND (%(since)s::text IS NULL OR d.date >= %(since)s)
ORDER BY d.id
"""

# The decisions on a motion dated on or after %(since)s (every one without it): their subject
# is the ``Onderwerp`` of the case they singled out.
_DECISIONS = f"""
SELECT d.id, d.key, lg_str(d.props -> 'subject') AS subject,
       lg_str(d.props -> 'motion_kind') AS kept
FROM {COLLECTION_DECISIONS} d
WHERE (lg_str(d.props -> 'kind') = '{KIND_MOTION}'
       OR lg_str(d.props -> 'primary_case_kind') = '{KIND_MOTION}')
  AND (%(since)s::text IS NULL OR d.date >= %(since)s)
ORDER BY d.id
"""


def motion_subjects(
    store: Store, collection: str, since: str | None
) -> list[dict[str, Any]]:
    """``{id, key, subject, kept}`` of every motion (*collection* ``documents``) or decision
    on one (``decisions``) dated on or after *since* (every one without it)."""
    statement = _DOCUMENTS if collection == COLLECTION_DOCUMENTS else _DECISIONS
    return list(store.query(statement, {"since": since}))
