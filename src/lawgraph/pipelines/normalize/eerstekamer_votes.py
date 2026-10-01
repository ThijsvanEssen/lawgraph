"""Normalize the votes of the Eerste Kamer on bills into decisions.

Every vote of the list (``ek-votes-day-html``) becomes a decision of the Eerste Kamer
(``chamber`` ``EK``) about the dossier of its bill: the outcome the Kamer shows
(``result``: ``Aangenomen``, ``Verworpen``), how it was decided (``method``, as the report
names it: ``Hamerstuk``, ``Stemming bij zitten en opstaan, aangenomen``), the factions that
voted for, against or asked to have their vote recorded, and the links to the bill and the
report. The list also holds the votes on the motions on a bill, under the bill's name and
number, which nothing on it tells apart; which vote decided the bill is for ``semantic
tk-dossier-outcomes``.

The list of rejected bills (``ek-rejected-html``) gives the dossier of each bill it names
``ek_rejected``: the day the Eerste Kamer rejected it (also before June 2015), with the
page and the day it was read.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_DOSSIERS,
    RAW_KIND_EK_REJECTED,
    RAW_KIND_EK_VOTES_DAY,
    RELATION_ABOUT,
    SOURCE_EERSTEKAMER,
)
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core import eerstekamer_votes
from lawgraph.core.eerstekamer_votes import (
    LABEL_AGAINST,
    LABEL_FOR,
    LABEL_NOTED,
    RESULT_ADOPTED,
    RESULT_REJECTED,
    Vote,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import NodeWriter
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "eerstekamer-votes"


def _url(path: str | None) -> str | None:
    return EERSTEKAMER_SITE.rstrip("/") + path if path else None


def decision_node(vote: Vote, position: int, retrieved_on: str | None) -> Node:
    """The decision of a vote, the *position*-th on its bill that day (from 1)."""
    return Node(
        collection=COLLECTION_DECISIONS,
        type=NodeType.DECISION,
        key=make_node_key("ek", vote.date, vote.label, str(position)),
        labels=["EK"],
        props={
            "chamber": "EK",
            "date": vote.date,
            "subject": vote.title,
            "display_name": f"Eerste Kamer {vote.date}: {vote.title} ({vote.number})",
            "dossier_numbers": [vote.label],
            "result": vote.result,
            "passed": vote.result == RESULT_ADOPTED,
            "method": vote.method,
            "factions_for": vote.factions.get(LABEL_FOR) or [],
            "factions_against": vote.factions.get(LABEL_AGAINST) or [],
            "factions_noted": vote.factions.get(LABEL_NOTED) or [],
            "bill_url": _url(vote.bill_path),
            "source_url": _url(vote.report_path),
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
        for record in raw:
            text = self._payload_text(record) or ""
            meta = self._meta(record)
            read_on = meta.get("read_on")
            if record.get("kind") == RAW_KIND_EK_REJECTED:
                rejected = eerstekamer_votes.rejected(text)
                rejected_from = {"source_url": meta.get("url"), "retrieved_on": read_on}
                continue
            seen: dict[str, int] = {}
            for vote in eerstekamer_votes.votes(str(record["external_id"]), text):
                seen[vote.label] = seen.get(vote.label, 0) + 1
                decisions.append(decision_node(vote, seen[vote.label], read_on))
        with NodeWriter(self.store) as writer:
            writer.add_all(decisions)
        self._mark_rejected(rejected, rejected_from)
        self._compare(decisions, rejected)
        logger.info(
            "Eerste Kamer: %d votes, %d rejected bills.", len(decisions), len(rejected)
        )
        return decisions

    def _mark_rejected(self, rejected: list[Vote], source: dict[str, Any]) -> None:
        """``ek_rejected`` on the dossier of every rejected bill the graph holds."""
        on: dict[str, str] = {}
        for bill in rejected:
            key = make_node_key(bill.label)
            on[key] = max(on.get(key, ""), bill.date)
        known = self.store.existing_keys(COLLECTION_DOSSIERS, set(on))
        nodes = [
            Node(
                collection=COLLECTION_DOSSIERS,
                type=NodeType.DOSSIER,
                key=key,
                labels=[],
                props={"ek_rejected": {"date": on[key], **source}},
                _skip_validation=True,
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
