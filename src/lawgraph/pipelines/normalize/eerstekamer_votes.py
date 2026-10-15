"""Normalize the votes of the Eerste Kamer on bills into decisions.

Every vote of the list (``ek-votes-day-html``) becomes a decision of the Eerste Kamer
(``chamber`` ``EK``) about the dossier of its bill: the outcome the Kamer shows
(``result``: ``Aangenomen``, ``Verworpen``), how it was decided (``method``, as the report
names it: ``Hamerstuk``, ``Stemming bij zitten en opstaan, aangenomen``), the factions that
voted for, against or asked to have their vote recorded, and the links to the bill and the
report, and a ``VOTED`` edge from each faction it names (``ek_<slug>``, by the name the list
writes, its ``abbreviation``) with the ``choice`` (``Voor``, ``Tegen``, ``Aantekening
gevraagd``) and the faction's ``seats`` when the vote falls in the period the composition
observed it (0 before). A vote on a motion (``kind`` ``Motie``, keyed by its letter) is
also ``ABOUT`` the motion itself, the Kamerstuk of the Eerste Kamer with that letter in its
dossier (``Kamerstuk I 37020, M``). Which vote decided a bill is for ``semantic
tk-dossier-outcomes``, of the votes on the bill.

The votes of a day are derived in full each time the day is read: a decision of that day
that the list no longer gives goes, with its edges (one made before the votes on motions
were told apart, a motion counted as a vote on its bill). A day not read, or whose page
gives no vote, is skipped and left as it is.

The list of rejected bills (``ek-rejected-html``) gives the dossier of each bill it names
``ek_rejected``: the day the Eerste Kamer rejected it (also before June 2015), with the
page and the day it was read.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_DECISIONS,
    COLLECTION_DOSSIERS,
    RAW_KIND_EK_REJECTED,
    RAW_KIND_EK_VOTES_DAY,
    RELATION_ABOUT,
    RELATION_VOTED,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_votes
from lawgraph.core.ek_votes import (
    LABEL_AGAINST,
    LABEL_FOR,
    LABEL_NOTED,
    RESULT_ADOPTED,
    RESULT_REJECTED,
    Vote,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.official_urls import ek_url
from lawgraph.core.tk_records.kinds import KIND_MOTION
from lawgraph.core.votes import VOTE_AGAINST, VOTE_FOR, VOTE_NOTED
from lawgraph.db import NodeWriter, make_edge_doc
from lawgraph.db.edges import EdgeWriter
from lawgraph.db.queries import removals
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.base import PipelineBase
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "eerstekamer-votes"


# Each list of a vote: the choice of a faction in it, as the VOTED edge carries it, and
# the prop of the decision that names its factions.
CHOICES = {
    LABEL_FOR: (VOTE_FOR, "factions_for"),
    LABEL_AGAINST: (VOTE_AGAINST, "factions_against"),
    LABEL_NOTED: (VOTE_NOTED, "factions_noted"),
}


def decision_node(vote: Vote, position: int, retrieved_on: str | None) -> Node:
    """The decision of a vote: on a bill the *position*-th on it that day (from 1), on a
    motion the one on its letter."""
    if vote.letter:
        key = make_node_key("ek", vote.date, vote.label, vote.letter)
        number = f"{vote.number}, {vote.letter}"
        motion: dict[str, Any] = {
            "kind": KIND_MOTION,
            "letter": vote.letter,
            "motion_url": ek_url(vote.motion_path),
        }
    else:
        key = make_node_key("ek", vote.date, vote.label, str(position))
        number, motion = vote.number, {}
    return Node(
        collection=COLLECTION_DECISIONS,
        key=key,
        labels=[CHAMBER_EK],
        props={
            **motion,
            "chamber": CHAMBER_EK,
            "date": vote.date,
            "subject": vote.title,
            "display_name": f"Eerste Kamer {vote.date}: {vote.title} ({number})",
            "dossier_numbers": [vote.label],
            "result": vote.result,
            "passed": vote.result == RESULT_ADOPTED,
            "method": vote.method,
            **{
                field: vote.factions.get(label) or []
                for label, (_, field) in CHOICES.items()
            },
            "bill_url": ek_url(vote.bill_path),
            "source_url": ek_url(vote.report_path),
            "retrieved_on": retrieved_on,
        },
    )


class EerstekamerVotesNormalizePipeline(NormalizePipelineBase):
    """The votes of the Eerste Kamer as decisions; the rejected bills on their dossiers."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EK_VOTES_DAY, RAW_KIND_EK_REJECTED],
            since=since,
            batch_size=50,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> list[Node]:
        decisions: list[Node] = []
        rejected: list[Vote] = []
        rejected_from: dict[str, Any] = {}
        days: list[str] = []
        for record in raw:
            text = self._payload_text(record)
            if not text:
                self.progress.skip("no page", record.get("external_id"))
                continue
            meta = self._meta(record)
            read_on = meta.get("read_on")
            if record.get("kind") == RAW_KIND_EK_REJECTED:
                rejected = ek_votes.rejected(text)
                rejected_from = {"source_url": meta.get("url"), "retrieved_on": read_on}
                continue
            day = str(record["external_id"])
            votes = ek_votes.votes(day, text)
            if not votes:
                self.progress.skip("no votes on the page", day)
                continue
            days.append(day)
            seen: dict[str, int] = {}
            for vote in votes:
                if vote.letter is None:  # a motion has a letter, not a place
                    seen[vote.label] = seen.get(vote.label, 0) + 1
                decisions.append(decision_node(vote, seen.get(vote.label, 0), read_on))
        with NodeWriter(self.store) as writer:
            writer.add_all(decisions)
        self._remove_gone(days, decisions)
        self._mark_rejected(rejected, rejected_from)
        self._compare(decisions, rejected)
        logger.info(
            "Eerste Kamer: %d votes, %d rejected bills.", len(decisions), len(rejected)
        )
        return decisions

    def _remove_gone(self, days: list[str], decisions: list[Node]) -> None:
        """Remove the decisions of the *days* read that the list no longer gives, with their
        edges; log per day how many went and how many there are."""
        made = {node.key for node in decisions}
        gone = [
            key
            for key in normalize_ek.ek_vote_keys_on(self.store, sorted(set(days)))
            if key not in made
        ]
        removals.remove_nodes(self.store, COLLECTION_DECISIONS, gone)
        per_day: dict[str, list[int]] = {}
        for node in decisions:
            per_day.setdefault(str(node.props["date"]), [0, 0])[0] += 1
        for key in gone:
            day = next(
                (d for d in set(days) if key.startswith(make_node_key("ek", d))), ""
            )
            per_day.setdefault(day, [0, 0])[1] += 1
        for day, (count, removed) in sorted(per_day.items()):
            if removed:
                logger.info(
                    "Eerste Kamer votes of %s: %d, %d no longer in the list removed.",
                    day,
                    count,
                    removed,
                )
        logger.info(
            "Eerste Kamer votes: %d days read, %d decisions, %d removed.",
            len(set(days)),
            len(decisions),
            len(gone),
        )

    def _mark_rejected(self, rejected: list[Vote], source: dict[str, Any]) -> None:
        """``ek_rejected`` on the dossier of every rejected bill the graph holds."""
        on: dict[str, str] = {}
        for bill in rejected:
            key = make_node_key(bill.label)
            on[key] = max(on.get(key, ""), bill.date)
        known = self.store.existing_keys(COLLECTION_DOSSIERS, set(on))
        nodes = [
            Node.skeleton(
                COLLECTION_DOSSIERS, key, {"ek_rejected": {"date": on[key], **source}}
            )
            for key in sorted(known)
        ]
        with NodeWriter(self.store) as writer:
            writer.add_all(nodes)
        logger.info("Marked %d dossiers rejected by the Eerste Kamer.", len(nodes))

    @staticmethod
    def _compare(decisions: list[Node], rejected: list[Vote]) -> None:
        """Log a rejected bill of the days read that no vote of that day rejects: the two
        lists of the Kamer disagree."""
        days = {node.props["date"] for node in decisions}
        voted = {
            (node.props["date"], node.props["dossier_numbers"][0])
            for node in decisions
            if node.props["result"] == RESULT_REJECTED
        }
        missing = sorted(
            f"{bill.label} ({bill.date})"
            for bill in rejected
            if bill.date in days and (bill.date, bill.label) not in voted
        )
        if missing:
            logger.warning(
                "%d rejected bills have no vote Verworpen that day in the list of "
                "votes: %s.",
                len(missing),
                ", ".join(missing[:20]),
            )

    def build_edges(self, raw: Any, normalized: list[Node]) -> None:
        tk_cases.link_subjects(
            self.store, normalized, RELATION_ABOUT, source=EDGE_SOURCE
        )
        link_motions(self, normalized, source=EDGE_SOURCE)
        link_faction_votes(self, normalized, source=EDGE_SOURCE)


def link_motions(pipeline: PipelineBase, decisions: list[Node], *, source: str) -> None:
    """``ABOUT`` from the decision on a motion to the motion, the Kamerstuk of the Eerste
    Kamer with its letter in its dossier; one not in the graph is skipped."""
    store = pipeline.store
    motions = [node for node in decisions if node.props.get("letter")]
    numbers = sorted(
        {str(node.props["dossier_numbers"][0]).split("-")[0] for node in motions}
    )
    documents = normalize_ek.ek_papers_by_letter(store, numbers) if numbers else {}
    writer = EdgeWriter(store, what="EK motions")
    for node in motions:
        document = documents.get(
            (node.props["dossier_numbers"][0], node.props["letter"])
        )
        if document is None or not node.node_id:
            pipeline.progress.skip("motion not in the graph", node.key)
            continue
        writer.add_doc(
            make_edge_doc(node.node_id, document, RELATION_ABOUT, source=source)
        )
    writer.flush()
    logger.info("Eerste Kamer votes on motions: %d about their motion.", writer.added)


def link_faction_votes(
    pipeline: PipelineBase, decisions: list[Node], *, source: str
) -> None:
    """VOTED from each faction a vote names to its decision; derived in full per decision,
    so a faction the list no longer names loses its edge. A name no faction of the Eerste
    Kamer has (one gone before the composition was first read) makes none and is skipped."""
    store = pipeline.store
    factions: dict[str, list[dict[str, Any]]] = {}
    for row in normalize_ek.ek_factions(store):
        factions.setdefault(row["abbreviation"], []).append(row)
    writer = EdgeWriter(store, what="EK faction votes")
    written: dict[str, list[str]] = {}
    for node in decisions:
        if not node.node_id:
            continue
        keys = written.setdefault(node.node_id, [])
        date = node.props.get("date")
        for choice, field in CHOICES.values():
            for name in node.props.get(field) or []:
                faction = ek_votes.faction_of(factions, name, date)
                if faction is None:
                    pipeline.progress.skip("name of no faction", f"{name} ({date})")
                    continue
                edge = make_edge_doc(
                    faction["id"],
                    node.node_id,
                    RELATION_VOTED,
                    source=source,
                    meta={
                        "choice": choice,
                        "seats": (faction["seats"] or 0)
                        if ek_votes.observed_on(faction, date)
                        else 0,
                    },
                )
                keys.append(edge["_key"])
                writer.add_doc(edge)
    writer.flush()
    removed = removals.remove_edges_into_except(store, RELATION_VOTED, written)
    logger.info(
        "Wrote %d VOTED edges of EK factions; removed %d.", writer.added, removed
    )
