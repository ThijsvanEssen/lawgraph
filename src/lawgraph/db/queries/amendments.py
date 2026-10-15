"""The amendments of a dossier as the Kamer handled them (``GET
/api/dossiers/{number}/amendments``): the chains of ``lg_amendment_chains``
(``feed_events.CHAINS``, written with the events) whose last document is a document of the
dossier, each with its documents, the decision that decides it and whether it still waits for
one."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    RELATION_ABOUT,
    RELATION_PART_OF,
    RELATION_REVISES,
)
from lawgraph.core.models import make_node_key, node_id
from lawgraph.db import GraphStore
from lawgraph.db.queries._json_sql import array_or_empty
from lawgraph.db.queries.dossiers import DOSSIER_DOCUMENT_IDS
from lawgraph.db.queries.feed_events import chosen_decisions
from lawgraph.db.queries.members import load_member_slugs

# Every document of the chains whose last document is a document of the dossier: the light props of
# each, the documents of its chain it replaces (REVISES), and of the last document its signatures
# and cases.
_DOCUMENTS = f"""
WITH docs AS MATERIALIZED ({DOSSIER_DOCUMENT_IDS}),
own AS (
    SELECT DISTINCT c.chain_id FROM lg_amendment_chains c JOIN docs ON docs.id = c.chain_id
)
SELECT c.chain_id, c.paper_id, c.first_date, c.outcome, p.key, p.labels,
       l.props AS light,
       CASE WHEN c.paper_id = c.chain_id THEN p.pj_actors END AS actors,
       CASE WHEN c.paper_id = c.chain_id
            THEN {array_or_empty("p.props -> 'case_ids'")} END AS case_ids,
       ARRAY(
           SELECT DISTINCT r.to_id
           FROM edges r
           JOIN lg_amendment_chains o ON o.chain_id = c.chain_id AND o.paper_id = r.to_id
           WHERE r.from_id = c.paper_id AND r.relation = %(revises)s
           ORDER BY r.to_id
       ) AS replaces
FROM own
JOIN lg_amendment_chains c ON c.chain_id = own.chain_id
JOIN {COLLECTION_DOCUMENTS} p ON p.id = c.paper_id
LEFT JOIN lg_document_light l ON l.id = c.paper_id
"""

# Per last document the decision that decides its chain: of its cases in their order the first
# with a decision that singles it out, as ``CHAINS`` gives the outcome; read among the
# decisions ABOUT its cases.
_DECISIONS = f"""
WITH listed AS (
    SELECT p.id AS chain_id, k.case_id, k.n
    FROM {COLLECTION_DOCUMENTS} p
    CROSS JOIN LATERAL json_array_elements_text(
        {array_or_empty("p.props -> 'case_ids'")}) WITH ORDINALITY AS k(case_id, n)
    WHERE p.id = ANY(%(chains)s::text[])
),
chosen AS ({
    chosen_decisions(
        "d.id IN (SELECT a.from_id FROM edges a"
        " WHERE a.to_id = ANY(%(cases)s::text[]) AND a.relation = %(about)s)"
    )
})
SELECT DISTINCT ON (listed.chain_id) listed.chain_id, d.id, d.key, d.date, d.passed,
       d.props -> 'decision_kind' AS decision_kind, d.props -> 'result' AS result,
       d.props -> 'tally' AS tally
FROM listed
JOIN chosen ON chosen.case_id = listed.case_id
JOIN decisions d ON d.id = chosen.id
ORDER BY listed.chain_id, listed.n
"""

# The cases the Kamer has not done with (``done`` false).
_OPEN_CASES = f"""
SELECT c.id FROM {COLLECTION_CASES} c
WHERE c.id = ANY(%(cases)s::text[]) AND json_typeof(c.props -> 'done') = 'boolean'
  AND NOT (c.props ->> 'done')::boolean
"""


def get_amendment_chains(store: GraphStore, dossier_id: str) -> list[dict[str, Any]]:
    """The chains of the amendments of the dossier *dossier_id*, as ``lg_amendment_chains``
    has them: ``{chain_id, first_date, outcome, documents, decision, open, member_slugs}``; ``documents`` each
    ``{id, key, labels, light, replaces}``, the last with its ``actors`` and ``case_ids``;
    ``decision`` (``{id, key, date, passed, decision_kind, result, tally}``) the one that
    decides it, else None; ``open`` whether a case of its last document is not done; ``member_slugs`` the slug of
    each member that signed its last document, by key."""
    chains: dict[str, dict[str, Any]] = {}
    rows = store.query(
        _DOCUMENTS,
        {
            "dossier_id": dossier_id,
            "part_of": RELATION_PART_OF,
            "revises": RELATION_REVISES,
        },
    )
    for row in rows:
        chain = chains.setdefault(
            row["chain_id"],
            {
                "chain_id": row["chain_id"],
                "first_date": row["first_date"],
                "outcome": row["outcome"],
                "documents": [],
            },
        )
        document = {name: row[name] for name in ("key", "labels", "light", "replaces")}
        document["id"] = row["paper_id"]
        if row["paper_id"] == row["chain_id"]:
            document |= {"actors": row["actors"], "case_ids": row["case_ids"]}
            chain["last"] = document
        chain["documents"].append(document)
    if not chains:
        return []
    cases = sorted(
        {
            node_id(COLLECTION_CASES, make_node_key(str(case)))
            for chain in chains.values()
            for case in chain["last"]["case_ids"] or []
        }
    )
    decided = {
        row["chain_id"]: row
        for row in store.query(
            _DECISIONS,
            {"chains": list(chains), "cases": cases, "about": RELATION_ABOUT},
        )
    }
    open_cases = set(store.query(_OPEN_CASES, {"cases": cases}))
    slugs = load_member_slugs(store)
    for chain_id, chain in chains.items():
        decision = decided.get(chain_id)
        chain["decision"] = (
            {key: value for key, value in decision.items() if key != "chain_id"}
            if decision
            else None
        )
        signed = {
            make_node_key(str(actor["person_id"]))
            for actor in chain["last"]["actors"] or []
            if actor.get("person_id")
        }
        chain["member_slugs"] = {k: slugs[k] for k in sorted(signed) if k in slugs}
        chain["open"] = any(
            node_id(COLLECTION_CASES, make_node_key(str(case))) in open_cases
            for case in chain["last"]["case_ids"] or []
        )
    return list(chains.values())
