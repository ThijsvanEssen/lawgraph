"""Normalize pipeline for Wikidata: the cabinet posts of the members.

Every person Wikidata has in a Dutch cabinet is matched to one Tweede Kamer person
(``core.government.match_member``: date of birth and surname); the member gets
``wikidata_id`` and ``government_functions``. A member no person matches any more loses
both. Which member a person is depends on all members, so every record is read on every
run, whatever ``since`` is; there are a few hundred.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_WIKIDATA_CABINET_POSTS,
    SOURCE_WIKIDATA,
)
from lawgraph.core.government import government_functions, match_member
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class WikidataNormalizePipeline(NormalizePipelineBase):
    """Write the cabinet posts from Wikidata onto the members they belong to."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_WIKIDATA,
            kinds=[RAW_KIND_WIKIDATA_CABINET_POSTS],
            batch_size=500,
        )

    def normalize_nodes(
        self, raw: Iterator[dict[str, Any]], result: PipelineResult
    ) -> int:
        members = list(normalize_queries.member_identities(self.store))
        by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for member in members:
            if member.get("birth_date"):
                by_year[member["birth_date"][:4]].append(member)

        matched: dict[str, Node] = {}
        unmatched: list[str] = []
        for record in raw:
            person = self._payload_json(record)
            if not isinstance(person, dict) or not person.get("id"):
                result.skipped += 1
                continue
            year = (person.get("birth_date") or "")[:4]
            key = match_member(person, by_year.get(year, []))
            if key is None:
                unmatched.append(person.get("name") or person["id"])
                continue
            matched[key] = self._member(key, person["id"], government_functions(person))

        cleared = [
            self._member(m["key"], None, None)
            for m in members
            if m.get("wikidata_id") and m["key"] not in matched
        ]
        self._upsert_nodes([*matched.values(), *cleared])
        logger.info(
            "Wikidata: %d people matched to a member, %d not (no Tweede Kamer person "
            "with that date of birth and surname), %d members cleared.",
            len(matched),
            len(unmatched),
            len(cleared),
        )
        if unmatched:
            logger.debug("Not matched: %s.", ", ".join(sorted(unmatched)))
        return len(matched)

    @staticmethod
    def _member(
        key: str, wikidata_id: str | None, functions: list[dict[str, Any]] | None
    ) -> Node:
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=[],
            props={"wikidata_id": wikidata_id, "government_functions": functions},
        )

    def build_edges(self, raw: Any, normalized: int) -> None:
        """Posts are props of the member, not edges."""
