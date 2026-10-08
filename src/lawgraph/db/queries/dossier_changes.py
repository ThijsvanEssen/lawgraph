"""The articles a bill changes (``GET /api/dossiers/{number}/changed-articles``).

Two stages. **Enacted**: a publication in the Staatsblad that is ``LEGISLATED_IN`` the
dossier, and the articles it amends, introduces or repeals, each with the date its change
takes effect (``meta.effective_date`` of the edge). **Proposed**: an edge with status
``voorgesteld`` out of a paper of the dossier (``PART_OF`` or ``ABOUT``): the change a bill
or an amendment proposes. A citation (``REFERS_TO``) or an explanation is no change.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_REPEALS,
)
from lawgraph.core.documents import chamber_of, paper_number
from lawgraph.db import GraphStore

STAGE_ENACTED = "enacted"
STAGE_PROPOSED = "proposed"
CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

# One row per change: the article, the relation, the stage, and what makes it (the
# publication or the paper). Both halves start from the dossier on ``edges_to_cover`` and
# follow their sources on ``edges_from_cover``. The judgments that cite an article are
# counted once per article, on ``edges_to_cover`` alone (one REFERS_TO edge per judgment
# and article).
_CHANGES_SQL = f"""
WITH changes AS (
    SELECT DISTINCT '{STAGE_ENACTED}' AS stage, e.relation, e.to_id AS article_id,
           e.from_id AS source_id,
           lg_str(e.doc -> 'meta' -> 'effective_date') AS effective_date
    FROM edges l
    JOIN edges e ON e.from_id = l.from_id
     AND e.relation = ANY(%(changes)s) AND e.to_collection = '{COLLECTION_ARTICLES}'
    WHERE l.to_id = %(dossier_id)s AND l.relation = %(legislated_in)s
      AND l.from_collection = '{COLLECTION_INSTRUMENTS}'
    UNION
    SELECT '{STAGE_PROPOSED}', e.relation, e.to_id, e.from_id, NULL
    FROM edges m
    JOIN edges e ON e.from_id = m.from_id
     AND e.relation = ANY(%(changes)s) AND e.to_collection = '{COLLECTION_ARTICLES}'
    WHERE m.to_id = %(dossier_id)s AND m.relation = ANY(%(members)s)
      AND e.status = %(proposed)s
),
cited AS (
    SELECT ca.article_id, (
        SELECT count(*)::int FROM edges j
        WHERE j.to_id = ca.article_id AND j.relation = %(refers_to)s
          AND j.from_collection = '{COLLECTION_JUDGMENTS}'
    ) AS judgment_total
    FROM (SELECT DISTINCT article_id FROM changes) ca
)
SELECT c.stage, c.relation, c.effective_date,
       c.article_id, a.key AS article_key, a.bwb_id, a.celex, a.article_number,
       lg_str(a.props -> 'display_name') AS article_name,
       coalesce(a.stub, false) AS stub, cited.judgment_total,
       i.id AS law_id, lg_str(i.props -> 'display_name') AS law_name,
       lg_str(i.props -> 'citation_title') AS law_title,
       c.source_id, s.key AS source_key, lg_str(s.props -> 'display_name') AS source_name,
       lg_str(s.props -> 'official_id') AS official_id,
       lg_str(s.props -> 'kind') AS source_kind, s.props -> 'sequence' AS source_sequence,
       lg_str(s.props -> 'number') AS source_number, s.labels AS source_labels
FROM changes c
JOIN cited ON cited.article_id = c.article_id
LEFT JOIN articles a ON a.id = c.article_id
LEFT JOIN instruments i ON i.bwb_id = a.bwb_id
LEFT JOIN LATERAL (
    SELECT n.key, n.props, n.labels FROM nodes n WHERE n.id = c.source_id LIMIT 1
) s ON true
ORDER BY i.citation_title NULLS LAST, a.bwb_id NULLS LAST,
         a.position IS NULL, a.position NULLS FIRST, a.key, c.article_id,
         c.stage NULLS LAST, c.relation NULLS LAST, c.source_id
"""


def get_dossier_changed_articles(
    store: GraphStore, dossier_id: str
) -> list[dict[str, Any]]:
    """The changes of the dossier per law: ``[{law, changes}]``, the laws by title, the
    changes in the order of the law (a law that is not in the graph last, by id). Each
    change: ``{article, relation, stage, source, effective_date}``, the relation in lower
    case (``amends``), as the dossier hub names it."""
    rows = store.query(
        _CHANGES_SQL,
        {
            "dossier_id": dossier_id,
            "changes": list(CHANGE_RELATIONS),
            "legislated_in": RELATION_LEGISLATED_IN,
            "members": [RELATION_PART_OF, RELATION_ABOUT],
            "proposed": EDGE_STATUS_VOORGESTELD,
            "refers_to": RELATION_REFERS_TO,
        },
    )
    laws: dict[str, dict[str, Any]] = {}
    for row in rows:
        law_key = row["bwb_id"] or row["celex"] or ""
        law = laws.setdefault(
            law_key,
            {
                "law": {
                    "id": row["law_id"],
                    "bwb_id": row["bwb_id"],
                    "celex": row["celex"],
                    "display_name": row["law_name"] or row["law_title"],
                },
                "changes": [],
            },
        )
        law["changes"].append(_change(row))
    return list(laws.values())


def _change(row: dict[str, Any]) -> dict[str, Any]:
    sequence = row["source_sequence"]
    return {
        "article": {
            "id": row["article_id"],
            "key": row["article_key"],
            "article_number": row["article_number"],
            "display_name": row["article_name"],
            "stub": row["stub"],
            "judgment_total": row["judgment_total"] or 0,
        },
        "relation": row["relation"].lower(),
        "stage": row["stage"],
        "source": {
            "id": row["source_id"],
            "key": row["source_key"],
            "display_name": row["source_name"],
            "official_id": row["official_id"],
            "kind": row["source_kind"],
            "sequence": sequence if isinstance(sequence, int) else None,
            "number": paper_number(
                chamber_of(row["source_labels"]),
                {"sequence": sequence, "number": row["source_number"]},
            ),
        },
        "effective_date": row["effective_date"],
    }
