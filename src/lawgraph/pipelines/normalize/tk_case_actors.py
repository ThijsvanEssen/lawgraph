"""Normalize the actors of Tweede Kamer cases (``retrieve tk-case-actors``) into edges.

AUTHORED from a member to the case they submitted (``meta.role`` as the source writes it,
``Indiener`` or ``Medeindiener``; ``function`` and ``capacity`` as on a document), and
LED_BY from a case to its voortouwcommissie (none when the plenary leads). Edges only
between nodes that exist; an actor whose case, member or committee is not yet stored is
linked by a later run.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    RAW_KIND_TK_CASE_ACTORS,
    RELATION_AUTHORED,
    RELATION_LED_BY,
    SOURCE_TK,
)
from lawgraph.core import tk_records
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.db import EdgeWriter, Store
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "tk-case-actors"

# Actor records written as edges at a time: the existence lookups are per batch.
_BATCH = 5000


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
                writer.add(
                    f"{COLLECTION_MEMBERS}/{member}",
                    f"{COLLECTION_CASES}/{case}",
                    RELATION_AUTHORED,
                    source=source,
                    meta={
                        "role": submitter["role"],
                        "function": submitter["function"],
                        "capacity": submitter["capacity"],
                    },
                )
        for committee in map(make_node_key, of["committee_ids"]):
            if committee in committees:
                writer.add(
                    f"{COLLECTION_CASES}/{case}",
                    f"{COLLECTION_COMMITTEES}/{committee}",
                    RELATION_LED_BY,
                    source=source,
                )
    writer.flush()
    return writer.added


class TKCaseActorsNormalizePipeline(NormalizePipelineBase):
    """Write AUTHORED and LED_BY edges from the stored actors of TK cases."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_CASE_ACTORS],
            since=since,
            batch_size=_BATCH,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        """No nodes: the actors are edges, written batch by batch as they are read."""
        count = edges = 0
        for records in chunked(raw, _BATCH):
            actors = [
                (str(payload["Id"]), tk_records.case_actors(payload))
                for record in records
                if (payload := payload_json(record))
                and payload.get("Id")
                and not tk_records.is_deleted(payload)
            ]
            result.skipped += len(records) - len(actors)
            edges += link_case_actors(self.store, actors, source=EDGE_SOURCE)
            count += len(actors)
        logger.info(
            "Case actors: %d cases read, %d edges (AUTHORED, LED_BY).", count, edges
        )
        return count

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """Written in ``normalize_nodes``, batch by batch."""
