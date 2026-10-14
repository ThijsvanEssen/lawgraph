"""Normalize the actors of Tweede Kamer cases (``retrieve tk-case-actors``) into edges.

AUTHORED from a member to the case they submitted (``meta.role`` as the source writes it,
``Indiener`` or ``Medeindiener``; ``function`` and ``capacity`` as on a document), and
LED_BY from a case to its voortouwcommissie (none when the plenary leads). Edges only
between nodes that exist; an actor whose case, member or committee is not yet stored is
linked by a later run.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    RAW_KIND_TK_CASE_ACTORS,
    RELATION_LED_BY,
)
from lawgraph.core import tk_records
from lawgraph.core.models import make_node_key, node_id
from lawgraph.db import EdgeWriter, Store
from lawgraph.pipelines.normalize._tk_cases import (
    LinkRecordsPipelineBase,
    authored_edge,
)


def link_case_actors(
    store: Store,
    actors: Iterable[tuple[str, dict[str, Any]]],
    *,
    source: str,
) -> int:
    """AUTHORED from each submitter to the case, LED_BY from the case to its lead
    committee, between nodes that exist. *actors* are ``(TK id of the case,
    tk_records.case_actors)``; returns the number of edges written."""
    actors = [(make_node_key(case_id), of) for case_id, of in actors]
    cases = store.existing_keys(COLLECTION_CASES, {case for case, _ in actors})
    actors = [(case, of) for case, of in actors if case in cases]
    members = store.existing_keys(
        COLLECTION_MEMBERS,
        {make_node_key(s["person_id"]) for _, of in actors for s in of["submitters"]},
    )
    committees = store.existing_keys(
        COLLECTION_COMMITTEES,
        {make_node_key(c) for _, of in actors for c in of["committee_ids"]},
    )

    writer = EdgeWriter(store, what="case actor edges")
    for case, of in actors:
        for submitter in of["submitters"]:
            member = make_node_key(submitter["person_id"])
            if member in members:
                writer.add_doc(
                    authored_edge(
                        member,
                        node_id(COLLECTION_CASES, case),
                        submitter,
                        source=source,
                    )
                )
        for committee in map(make_node_key, of["committee_ids"]):
            if committee in committees:
                writer.add(
                    node_id(COLLECTION_CASES, case),
                    node_id(COLLECTION_COMMITTEES, committee),
                    RELATION_LED_BY,
                    source=source,
                )
    writer.flush()
    return writer.added


class TKCaseActorsNormalizePipeline(LinkRecordsPipelineBase):
    """Write AUTHORED and LED_BY edges from the stored actors of TK cases."""

    kind = RAW_KIND_TK_CASE_ACTORS
    read = tk_records.case_actors
    link = link_case_actors
    edge_source = "tk-case-actors"
    what = "Case actors"
