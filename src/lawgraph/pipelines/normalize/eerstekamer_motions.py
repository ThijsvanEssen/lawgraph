"""Normalize the pages of the motions of the Eerste Kamer (``retrieve eerstekamer-motions``)
onto the motion itself, its Kamerstuk of the Eerste Kamer (``Kamerstuk I 37020, M``).

The page (``core.ek_motions``) gives the motion what it asks (``summary``, "In deze motie wordt
de regering verzocht …"), the day it was submitted (``submitted_on``), the debate it was
submitted at (``debate``), its status (``status``: ``verworpen``, ``aangenomen``), its page
(``motion_url``) and its PDF (``pdf_url``), and who submitted and co-signed it (``actors``,
as the Tweede Kamer gives the signatures of a motion: ``name``, ``faction``, ``role`` ``Eerste
ondertekenaar`` or ``Mede ondertekenaar``, and ``person_id``, the Tweede Kamer's id of their
member), and ``AUTHORED`` from each member.

A signer is the member of their page (``/persoon/…``), as ``normalize eerstekamer-persons``
matches a page to a member (``members_of_pages``: the composition's path, else the member born
on the day the page gives whose surname ends its name). A signer whose page is not stored, or
of no member, is a name without a member and no ``AUTHORED``, skipped. A motion whose Kamerstuk
is not in the graph is skipped, and nothing is written of it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_DOCUMENTS,
    COLLECTION_MEMBERS,
    LABEL_EERSTE_KAMER,
    RAW_KIND_EK_MOTION,
    RAW_KIND_EK_PERSON,
    RELATION_AUTHORED,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_motions, ek_persons
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, key_of, node_id
from lawgraph.core.official_urls import ek_url
from lawgraph.core.tk_records.actors import (
    CO_SIGNATORY,
    FIRST_SIGNATORY,
    SUBMITTER_CO,
    SUBMITTER_FIRST,
)
from lawgraph.db import NodeWriter
from lawgraph.db.edges import EdgeWriter
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize._ek_members import members_of_pages
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

EDGE_SOURCE = "eerstekamer-motions"

# The role of a signer as the Tweede Kamer writes it on the signatures of a motion
# (``tk_records.actors.submitters`` reads them).
ROLES = {
    SUBMITTER_FIRST: FIRST_SIGNATORY,
    SUBMITTER_CO: CO_SIGNATORY,
}


@dataclass(frozen=True)
class Written:
    """The motions written (the id of their Kamerstuk and their page), and the member of
    each signer's page that has one (``{path: {key, person_id}}``)."""

    motions: list[tuple[str, ek_motions.MotionPage]]
    members: dict[str, dict[str, Any]]


class EerstekamerMotionsNormalizePipeline(NormalizePipelineBase[Records]):
    """What the page of a motion of the Eerste Kamer says, on the motion's Kamerstuk."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EK_MOTION],
            since=since,
            batch_size=50,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The motions on their Kamerstuk, then who signed them."""
        self._link(self._write_nodes(raw, result))

    def _write_nodes(self, raw: Records, result: PipelineResult) -> Written:
        motions: list[tuple[str, ek_motions.MotionPage]] = []
        for record in raw:
            path = str(record["external_id"])
            page = ek_motions.motion_page(self._payload_text(record) or "")
            if page is None:
                self.progress.skip("no motion on the page", path)
            else:
                motions.append((path, page))
        papers = normalize_ek.ek_papers_by_letter(
            self.store, sorted({page.label.split("-")[0] for _, page in motions})
        )
        members = self._members({s.path for _, p in motions for s in p.signers})
        written: list[tuple[str, ek_motions.MotionPage]] = []
        with NodeWriter(self.store) as writer:
            for path, page in motions:
                paper = papers.get((page.label, page.letter))
                if paper is None:
                    self.progress.skip(
                        "Kamerstuk not in the graph", f"{page.number}, {page.letter}"
                    )
                    continue
                writer.add(_paper_node(paper, path, page, members))
                written.append((paper, page))
                result.updated += 1
        logger.info(
            "Eerste Kamer motions: %d pages, %d on their Kamerstuk.",
            len(motions),
            len(written),
        )
        return Written(written, members)

    def _members(self, paths: set[str]) -> dict[str, dict[str, Any]]:
        """``{path: {key, person_id}}`` of each signer's page that is a member's."""
        pages: dict[str, ek_persons.PersonPage | None] = dict.fromkeys(paths)
        for record in self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER, kinds=[RAW_KIND_EK_PERSON], batch_size=50
        ):
            path = str(record["external_id"])
            if path in paths and (
                page := ek_persons.person_page(self._payload_text(record) or "")
            ):
                pages[path] = page
        keys = members_of_pages(self.store, pages)
        ids = {
            row["key"]: row["external_id"]
            for row in normalize_ek.member_external_ids(
                self.store, sorted(keys.values())
            )
        }
        return {
            path: {"key": key, "person_id": ids.get(key)} for path, key in keys.items()
        }

    def _link(self, written: Written) -> None:
        """``AUTHORED`` from each member who submitted or co-signed a motion to it."""
        members = written.members
        writer = EdgeWriter(self.store, what="AUTHORED edges of motions")
        for paper, page in written.motions:
            for signer in page.signers:
                member = members.get(signer.path)
                if member is None:
                    self.progress.skip("signer of no member", signer.name)
                    continue
                writer.add(
                    node_id(COLLECTION_MEMBERS, member["key"]),
                    paper,
                    RELATION_AUTHORED,
                    source=EDGE_SOURCE,
                    meta={"role": ROLES[signer.role]},
                )
        writer.flush()


def _paper_node(
    paper: str,
    path: str,
    page: ek_motions.MotionPage,
    members: dict[str, dict[str, Any]],
) -> Node:
    """The props the page of a motion gives its Kamerstuk (written over what it had)."""
    actors = [
        {
            "name": signer.name,
            "faction": signer.faction,
            "role": ROLES[signer.role],
            "person_id": (members.get(signer.path) or {}).get("person_id"),
        }
        for signer in page.signers
    ]
    return Node(
        collection=COLLECTION_DOCUMENTS,
        key=key_of(paper),
        labels=[LABEL_EERSTE_KAMER, CHAMBER_EK],
        props={
            "summary": page.summary,
            "submitted_on": page.submitted_on,
            "debate": page.debate,
            "status": page.status,
            "motion_url": ek_url(path),
            "pdf_url": ek_url(page.pdf_path),
            "actors": actors,
        },
    )
