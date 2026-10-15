"""Which proposed change of an article still stands: the rule ``amended-by`` and
``legislative-history`` share.

A document of the Tweede Kamer that changes an article (``AMENDS``, ``INTRODUCES``, ``REPEALS``,
status ``voorgesteld``) is a pending proposal while

- no dossier of it is closed: a bill that was enacted changed the law through its
  publication (whose edge is the change), one that was rejected changed nothing;
- it is no amendment that was rejected, or that a newer version replaced (both from
  ``lg_amendment_chains``: its chain's outcome, and whether it is the last document of it);
- no decision on a case of it withdrew it (``Stemmen - ingetrokken``).
"""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.core.votes import ADOPTED, DECISION_KIND_WITHDRAWN, REJECTED


def pending_sql(document: str) -> str:
    """SQL: whether the document whose id is *document* (an SQL expression) is a pending
    proposal (see the module). Each test a probe per document (``OFFSET 0`` keeps the planner
    from turning it into a join over every closed dossier or every ``PART_OF`` edge)."""
    return f"""(
        NOT EXISTS (
            SELECT 1
            FROM {COLLECTION_DOCUMENTS} pd
            JOIN {COLLECTION_DOSSIERS} pds ON pds.label = ANY(pd.dossier_numbers)
            WHERE pd.id = {document} AND pds.closed
            OFFSET 0
        )
        AND NOT EXISTS (
            SELECT 1 FROM lg_amendment_chains pc
            WHERE pc.paper_id = {document}
              AND (pc.outcome = '{REJECTED}' OR pc.chain_id <> pc.paper_id)
            OFFSET 0
        )
        AND NOT EXISTS (
            SELECT 1
            FROM {COLLECTION_EDGES} pp
            JOIN {COLLECTION_EDGES} pa
              ON pa.to_id = pp.to_id AND pa.relation = '{RELATION_ABOUT}'
             AND pa.from_collection = '{COLLECTION_DECISIONS}'
            JOIN {COLLECTION_DECISIONS} pdec ON pdec.id = pa.from_id
            WHERE pp.from_id = {document} AND pp.relation = '{RELATION_PART_OF}'
              AND pp.to_collection = '{COLLECTION_CASES}'
              AND lg_str(pdec.props -> 'decision_kind') = '{DECISION_KIND_WITHDRAWN}'
            OFFSET 0
        )
    )"""


def outcome_sql(document: str) -> str:
    """SQL: the outcome of the amendment whose id is *document*, ``aangenomen`` once adopted,
    else null (a pending proposal is never rejected)."""
    return f"""(
        SELECT pc.outcome FROM lg_amendment_chains pc
        WHERE pc.paper_id = {document} AND pc.outcome = '{ADOPTED}'
        LIMIT 1
    )"""
