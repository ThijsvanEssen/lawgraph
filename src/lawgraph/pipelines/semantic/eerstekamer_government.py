"""Who in government made each commitment of the Eerste Kamer, in which post and ministry, and
under which cabinet.

A commitment of the Eerste Kamer names the office responsible (``minister_role``: ``Minister
van Sociale Zaken en Werkgelegenheid``) and, in the passage quoted, who spoke in an office of
that kind (``minister_name``: ``Vijlbrief``; ``normalize eerstekamer-commitments``). They are
read as those of the Tweede Kamer are (``semantic tk-government``, ``commitment_props``): the
member is the person who held a post of that kind on the day it was made and whose surname is
the name (``core.signatories.match_signatory``); ``post`` and ``ministry`` are those of the
office, or of the function the text names when that is another ministry, else the ministry
of the post the member held that day; ``cabinet`` is the cabinet in office on the day. A
member found is also an ``AUTHORED`` edge to the commitment (``meta.role`` ``toezegger``),
removed where the match is gone.

What does not fit is marked, never filled: ``member_missing`` says why there is no member
(``no_name``: the passage names no one in an office of that kind; ``unmatched``: the name fits
no one or several), and ``ministry_held`` gives the ministry of the post the member held
that day when it is not that of the office the Kamer names (the Kamer names some offices by
a later name).

Runs over every commitment of the Eerste Kamer (some 4,300) after ``normalize rijksoverheid``
has written the cabinets and posts, and writes only what changed.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITMENTS,
    COLLECTION_MEMBERS,
    RELATION_AUTHORED,
)
from lawgraph.core.ek_commitments import NO_NAME, UNMATCHED
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult, node_id
from lawgraph.core.signatories import post_kind
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import tk_government as government_queries
from lawgraph.sources.addresses import edge_source

from .base import SemanticPipelineBase
from .tk_government import ROLE_COMMITTED, commitment_props, held_ministry

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)

# The props this step writes on a commitment of the Eerste Kamer.
WRITTEN = (
    "member_key",
    "post",
    "ministry",
    "cabinet",
    "member_missing",
    "ministry_held",
)


def ek_commitment_props(
    row: dict[str, Any], people: list[dict[str, Any]], cabinets: list[dict[str, Any]]
) -> dict[str, Any]:
    """The props of ``WRITTEN`` of a commitment row of ``commitment_makers``."""
    props = commitment_props(row, people, cabinets)
    member = props["member_key"]
    held = held_ministry(member, row.get("date"), post_kind(row.get("role")), people)
    missing = None if member else UNMATCHED if row.get("name") else NO_NAME
    return {
        **props,
        "member_missing": missing,
        "ministry_held": held if held and held != props["ministry"] else None,
    }


class EerstekamerGovernmentSemanticPipeline(SemanticPipelineBase):
    """Write who made each commitment of the Eerste Kamer, and the post, ministry and cabinet."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        people = list(government_queries.government_people(self.store))
        cabinets = list(government_queries.cabinet_periods(self.store))
        updates = []
        makers = EdgeWriter(self.store, what=None, remembers=True)
        read: list[str] = []
        counts = {"total": 0, "member": 0, "ministry": 0, "conflict": 0}
        rows = government_queries.commitment_makers(self.store, ek=True, kept=WRITTEN)
        for row in self._track(list(rows), "commitments"):
            props = ek_commitment_props(row, people, cabinets)
            counts["total"] += 1
            counts["member"] += props["member_key"] is not None
            counts["ministry"] += props["ministry"] is not None
            counts["conflict"] += props["ministry_held"] is not None
            if props != row.get("props"):
                updates.append(
                    {
                        "key": row["key"],
                        "type": NodeType.COMMITMENT.value,
                        "labels": [],
                        "props": props,
                    }
                )
            commitment = node_id(COLLECTION_COMMITMENTS, row["key"])
            read.append(commitment)
            if props["member_key"]:
                makers.add(
                    node_id(COLLECTION_MEMBERS, props["member_key"]),
                    commitment,
                    RELATION_AUTHORED,
                    source=EDGE_SOURCE,
                    meta={"role": ROLE_COMMITTED, "function": row.get("role")},
                )
        if updates:
            self.store.bulk_insert_or_update_nodes(COLLECTION_COMMITMENTS, updates)
        makers.flush_into(result)
        makers.remove_stale_to([RELATION_AUTHORED], EDGE_SOURCE, read)
        result.updated = len(updates)
        logger.info(
            "%(total)d commitments of the Eerste Kamer: %(member)d with a member, "
            "%(ministry)d with a ministry, %(conflict)d whose member held another "
            "ministry that day.",
            counts,
        )
        return result
