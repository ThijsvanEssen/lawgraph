"""``semantic tk-coalition-votes``: what the coalition did on each vote of the Tweede Kamer.

For every decision with votes, the cabinet in office that day and its coalition
(``core.coalition.coalition_on``: the factions whose party held a post in it), then
``core.coalition.vote_pattern``: the seats for and against of the coalition and of the
opposition, whether the coalition voted together, split, or split with a wisselmeerderheid,
and whether it carried or decided the vote. A faction votes with its seats that day
(``meta.seats``, FractieGrootte); a roll call counts each member as one seat of the faction
they sat in that day. Kept in ``lg_decision_coalition`` (not a table of the graph), which the
list and the detail of decisions read.

With ``--since`` only the decisions dated from then on are written (the daily run); without
it every one, and the rows of decisions that no longer have a coalition vote go (the weekly
run, which also follows a change of the posts of a cabinet). The Eerste Kamer is left out:
its seats per day are not known.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from itertools import groupby
from typing import Any

from lawgraph.config.constants import COLLECTION_FACTIONS, COLLECTION_MEMBERS
from lawgraph.core.coalition import coalition_on, vote_pattern
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import coalition as coalition_queries
from lawgraph.db.queries.cabinets import memberships_between

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Rows written at a time.
_BATCH = 2000


class TKCoalitionVotesSemanticPipeline(SemanticPipelineBase):
    """What the coalition did on each vote, into ``lg_decision_coalition``."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        cabinets = coalition_queries.cabinets_with_posts(self.store)
        factions_of = _factions_of_members(
            memberships_between(self.store, "0000-01-01", "9999-12-31")
        )
        since_date = since.date().isoformat() if since is not None else None
        rows = coalition_queries.decision_votes(self.store, since_date)
        kept: list[str] = []
        batch: list[dict[str, Any]] = []
        for decision_id, votes in groupby(
            self._track(rows, "votes"), lambda r: r["id"]
        ):
            row = _decision_row(decision_id, list(votes), cabinets, factions_of)
            if row is None:
                continue
            batch.append(row)
            kept.append(decision_id)
            if len(batch) >= _BATCH:
                coalition_queries.keep_decision_coalition(self.store, batch)
                batch = []
        coalition_queries.keep_decision_coalition(self.store, batch)
        result.updated += len(kept)
        removed = 0
        if since is None:
            removed = coalition_queries.remove_decision_coalition_except(
                self.store, kept
            )
        logger.info(
            "Coalition on %d votes; removed %d no longer with one.", len(kept), removed
        )
        return result


def _factions_of_members(
    memberships: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Member key -> its faction memberships."""
    found: dict[str, list[dict[str, Any]]] = {}
    for row in memberships:
        found.setdefault(str(row["member"]), []).append(row)
    return found


def _cabinet_on(cabinets: list[dict[str, Any]], day: str) -> dict[str, Any] | None:
    """The cabinet in office on *day*: the newest that had begun and not yet ended."""
    for cabinet in cabinets:  # newest first
        if cabinet["from_date"] <= day and (
            not cabinet["to_date"] or day <= cabinet["to_date"]
        ):
            return cabinet
    return None


def _faction_on(memberships: list[dict[str, Any]], day: str) -> str | None:
    for row in memberships:
        if (row.get("from_date") or "") <= day and (
            not row.get("to_date") or day <= row["to_date"]
        ):
            return row.get("faction_key")
    return None


def _votes(
    votes: list[dict[str, Any]],
    day: str,
    factions_of: dict[str, list[dict[str, Any]]],
) -> Iterator[tuple[str, str, int]]:
    """``(faction key, choice, seats)``: a faction with its seats, a member as one seat of
    the faction they sat in that day."""
    for vote in votes:
        if vote["voter_collection"] == COLLECTION_FACTIONS:
            yield vote["voter"], vote["choice"] or "", int(vote["seats"] or 0)
        elif vote["voter_collection"] == COLLECTION_MEMBERS:
            faction = _faction_on(factions_of.get(vote["voter"], []), day)
            if faction:
                yield faction, vote["choice"] or "", 1


def _decision_row(
    decision_id: str,
    votes: list[dict[str, Any]],
    cabinets: list[dict[str, Any]],
    factions_of: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """The row of ``lg_decision_coalition`` of one decision; None without a cabinet or
    without a coalition vote."""
    day = str(votes[0]["date"])[:10]
    cabinet = _cabinet_on(cabinets, day)
    if cabinet is None:
        return None
    coalition = coalition_on(cabinet["posts"] or [], day)
    pattern = vote_pattern(_votes(votes, day, factions_of), coalition)
    if pattern is None:
        return None
    return {"id": decision_id, "cabinet": cabinet["key"], **pattern}
