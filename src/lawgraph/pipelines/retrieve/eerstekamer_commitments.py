"""Retrieve pipeline for the commitments (toezeggingen) of the Eerste Kamer: the page of each
commitment of its register on eerstekamer.nl (``/toezegging/…``, ``ek-commitment-html``,
external id its path; ``core.ek_commitments``).

The register lists every commitment since June 2003 with its status, the newest first, 50 a
page (some 90 pages). A page is fetched when it is not stored, or when the register gives
the commitment another status than the one stored with it (``meta.status``): the page then
says how it was kept. ``since`` reads the register only down to the commitments made that
day; without it the whole register is read, which finds every change of status. ``limit``
caps the pages of one run (the first run, some 4,300 pages at the host's interval, goes in
slices); the log says how many are left after it.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_COMMITMENT,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.ek_commitments import ListedCommitment
from lawgraph.core.logging import get_logger
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.command import add_limit_argument, add_since_argument

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

# The pages of one run by default: some 10 minutes at the host's interval.
PAGES_PER_RUN = 300


def ek_commitments_args(parser: argparse.ArgumentParser) -> None:
    """The options of ``retrieve eerstekamer-commitments``."""
    add_since_argument(
        parser,
        help="Read the register only down to the commitments made on this day (no change "
        "of status of an older one is seen); without it the whole register.",
    )
    add_limit_argument(
        parser,
        "At most this many pages in this run (the rest in the next).",
        default=PAGES_PER_RUN,
    )


class EerstekamerCommitmentsRetrievePipeline(RetrievePipelineBase):
    """Store the page of every commitment of the Eerste Kamer not stored yet or whose status
    changed."""

    def __init__(
        self,
        store: GraphStore,
        client: EerstekamerSiteClient | None = None,
        *,
        since: dt.datetime | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()
        self.since = since.date() if since else None
        self.limit = limit

    def listed(self) -> list[ListedCommitment]:
        """The commitments of the register, down to those made on ``since``."""
        found: list[ListedCommitment] = []
        for entry in self.client.listed_commitments():
            if self.since and entry.made_on and entry.made_on < self.since.isoformat():
                break
            found.append(entry)
        return found

    def wanted(self, listed: list[ListedCommitment]) -> list[ListedCommitment]:
        """Of *listed*, those whose page is not stored or was stored with another status."""
        stored = {
            str(row["id"]): row["value"]
            for row in raw_queries.meta_values(
                self.store,
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EERSTEKAMER_COMMITMENT,
                field="status",
            )
        }
        seen: set[str] = set()
        wanted = []
        for entry in listed:
            if entry.path not in seen and stored.get(entry.path, "") != entry.status:
                wanted.append(entry)
            seen.add(entry.path)
        return wanted

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dutch_today().isoformat()
        listed = self.listed()
        wanted = self.wanted(listed)
        now = wanted[: self.limit] if self.limit is not None else wanted
        logger.info(
            "Eerste Kamer commitments: %d listed, %d wanted, %d in this run, %d left "
            "after it",
            len(listed),
            len(wanted),
            len(now),
            len(wanted) - len(now),
        )
        for entry in now:
            url, page = self.client.page(entry.path)
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EERSTEKAMER_COMMITMENT,
                external_id=entry.path,
                payload_text=page,
                meta={
                    "url": url,
                    "read_on": today,
                    "number": entry.number,
                    "status": entry.status,
                },
            )
