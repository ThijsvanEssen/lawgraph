"""Who in government made each commitment and brought each dossier in, and under which cabinet.

A commitment (toezegging) names the one who made it as the Tweede Kamer writes it
(``Herbert, H.G.``, ``Minister van Economische Zaken en Klimaat``) on a date. The member is the
person who held a post of that kind on that day and whose surname is in the name
(``core.government.match_signatory``, as for the signatures of ministers from outside
parliament); ``member_key`` is null when no one or several fit. ``post`` and ``ministry`` are
read from the role (``core.ministries``), ``cabinet`` is the cabinet in office on the day.

A dossier is brought in by whoever signed its earliest signed document first: a
bewindspersoon gives it the ``ministry`` of their function that day, a Kamerlid makes it an
``initiative``; ``cabinet`` is the cabinet in office then. Both are null for a dossier none of
whose documents a Kamerlid or bewindspersoon signed first.

Runs over every commitment and dossier after ``normalize rijksoverheid`` has written the cabinets
and posts, and writes only what changed.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_COMMITMENTS, COLLECTION_DOSSIERS
from lawgraph.core.cabinets import cabinet_on
from lawgraph.core.government import match_signatory
from lawgraph.core.logging import get_logger
from lawgraph.core.ministries import classify_function
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER
from lawgraph.db.queries import government as government_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)


def commitment_props(
    row: dict[str, Any], people: list[dict[str, Any]], cabinets: list[dict[str, Any]]
) -> dict[str, Any]:
    """``member_key``, ``post``, ``ministry`` and ``cabinet`` of a commitment row of
    ``government_queries.commitment_makers``."""
    date = row.get("date")
    signature = {
        "name": row.get("name"),
        "function": row.get("role"),
        "first": date,
        "last": date,
    }
    post, ministry = classify_function(row.get("role"), on=date)
    return {
        "member_key": match_signatory([signature], people) if date else None,
        "post": post,
        "ministry": ministry,
        "cabinet": cabinet_on(date, cabinets),
    }


def dossier_props(
    first: dict[str, Any] | None, cabinets: list[dict[str, Any]]
) -> dict[str, Any]:
    """``ministry``, ``initiative`` and ``cabinet`` of a dossier whose earliest signed
    document was signed first as *first* (``{date, capacity, function}``)."""
    if not first:
        return {"ministry": None, "initiative": None, "cabinet": None}
    capacity = first.get("capacity")
    ministry = None
    if capacity == CAPACITY_GOVERNMENT:
        ministry = classify_function(first.get("function"), on=first.get("date"))[1]
    return {
        "ministry": ministry,
        "initiative": capacity == CAPACITY_MEMBER,
        "cabinet": cabinet_on(first.get("date"), cabinets),
    }


class TKGovernmentSemanticPipeline(SemanticPipelineBase):
    """Write who made each commitment and who brought each dossier in."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        people = list(government_queries.government_people(self.store))
        cabinets = list(government_queries.cabinet_periods(self.store))

        commitments = []
        matched = total = 0
        for row in self._track(
            list(government_queries.commitment_makers(self.store)), "commitments"
        ):
            props = commitment_props(row, people, cabinets)
            total += 1
            matched += props["member_key"] is not None
            if props != row.get("props"):
                commitments.append(self._update(row["key"], NodeType.COMMITMENT, props))
        dossiers = []
        brought = 0
        for row in self._track(
            list(government_queries.dossier_first_signatures(self.store)), "dossiers"
        ):
            props = dossier_props(row.get("first"), cabinets)
            brought += props["initiative"] is not None
            if props != row.get("props"):
                dossiers.append(self._update(row["key"], NodeType.DOSSIER, props))

        for collection, updates in (
            (COLLECTION_COMMITMENTS, commitments),
            (COLLECTION_DOSSIERS, dossiers),
        ):
            if updates:
                self.store.bulk_insert_or_update_nodes(collection, updates)
        result.updated = len(commitments) + len(dossiers)
        logger.info(
            "%d of %d commitments matched to a member; %d dossiers brought in by a "
            "bewindspersoon or Kamerlid; %d nodes changed.",
            matched,
            total,
            brought,
            result.updated,
        )
        return result

    @staticmethod
    def _update(key: str, node_type: NodeType, props: dict[str, Any]) -> dict[str, Any]:
        return {"_key": key, "type": node_type.value, "labels": [], "props": props}
