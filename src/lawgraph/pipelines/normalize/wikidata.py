"""Normalize pipeline for Wikidata: the cabinet posts of the members.

Every person Wikidata has in a Dutch cabinet is matched to one Tweede Kamer person
(``core.government``): a member of parliament by date of birth and surname, a minister who
never sat in parliament (a TK person without name or date) by the papers they signed. The
member gets ``wikidata_id``, ``wikidata_name`` and ``government_functions``; a member no
person matches any more loses them. A person who matches nobody becomes a member of their
own, keyed by the Q-id and labelled ``Wikidata``; once a later run finds their Tweede Kamer
person, that member is removed, so one person is never two members. Which member a person is
depends on all members, so every record is read on every run, whatever ``since`` is; there
are a few hundred.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    LABEL_WIKIDATA,
    RAW_KIND_WIKIDATA_CABINET_POSTS,
    SOURCE_WIKIDATA,
)
from lawgraph.core.government import (
    PRECISION_DAY,
    government_functions,
    match_member,
    match_signatory,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


def _one_each(claims: dict[str, list[str]], what: str) -> dict[str, str]:
    """*claims* (one side -> the other sides that claim it) kept where there is one claim;
    a side claimed twice is logged and left out."""
    for claimed, by in claims.items():
        if len(by) > 1:
            logger.warning(
                "Wikidata: %s %s is claimed by %s; none is kept.",
                what,
                claimed,
                ", ".join(sorted(by)),
            )
    return {claimed: by[0] for claimed, by in claims.items() if len(by) == 1}


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
        people: dict[str, dict[str, Any]] = {}
        for record in raw:
            person = self._payload_json(record)
            if not isinstance(person, dict) or not person.get("id"):
                result.skipped += 1
                continue
            people[person["id"]] = person

        members = list(normalize_queries.member_identities(self.store))
        by_member = self._match_members(people, members)
        by_signatures = self._match_signatories(
            [p for p in people.values() if p["id"] not in by_member.values()]
        )
        matched = {**by_member, **by_signatures}  # member key -> Q-id
        own = [p for qid, p in people.items() if qid not in matched.values()]

        nodes = [self._member(key, people[qid]) for key, qid in matched.items()]
        cleared = [
            self._member(m["key"], None)
            for m in members
            if m.get("wikidata_id") and m["key"] not in matched
        ]
        self._upsert_nodes([*nodes, *cleared, *(self._own_member(p) for p in own)])
        removed = self._remove_superseded({self._own_key(p["id"]) for p in own})
        logger.info(
            "Wikidata: %d people matched to a member of parliament, %d to a minister "
            "by their signatures, %d members of their own (%d removed: now matched); "
            "%d members cleared.",
            len(by_member),
            len(by_signatures),
            len(own),
            removed,
            len(cleared),
        )
        return len(nodes) + len(own)

    @staticmethod
    def _match_members(
        people: dict[str, dict[str, Any]], members: list[dict[str, Any]]
    ) -> dict[str, str]:
        """Member key -> Q-id, by date of birth and surname."""
        dated = [m for m in members if m.get("birth_date")]
        claims: dict[str, list[str]] = defaultdict(list)
        for qid, person in people.items():
            key = match_member(person, dated)
            if key is not None:
                claims[key].append(qid)
        return _one_each(claims, "member")

    def _match_signatories(self, people: list[dict[str, Any]]) -> dict[str, str]:
        """Member key -> Q-id, for the members without a name of their own, by the papers
        they signed as a minister or state secretary."""
        signatures: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in normalize_queries.government_signatures(self.store):
            signatures[row["key"]].append(row)
        claims: dict[str, list[str]] = defaultdict(list)
        for key, signed in signatures.items():
            qid = match_signatory(signed, people)
            if qid is not None:
                claims[qid].append(key)
        return {key: qid for qid, key in _one_each(claims, "person").items()}

    def _remove_superseded(self, keep: set[str]) -> int:
        """Remove the members of their own that are no longer a person of their own."""
        gone = [
            key
            for key in normalize_queries.wikidata_members(self.store)
            if key not in keep
        ]
        return normalize_queries.remove_members(self.store, gone) if gone else 0

    @staticmethod
    def _own_key(qid: str) -> str:
        return make_node_key(SOURCE_WIKIDATA, qid)

    @classmethod
    def _own_member(cls, person: dict[str, Any]) -> Node:
        name = person.get("name") or person["id"]
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=cls._own_key(person["id"]),
            labels=[LABEL_WIKIDATA],
            props={
                "external_id": person["id"],
                "name": name,
                "display_name": name,
                # a date Wikidata knows only to the year is no date of birth
                "birth_date": person.get("birth_date")
                if (person.get("birth_precision") or 0) >= PRECISION_DAY
                else None,
                **cls._wikidata_props(person),
            },
        )

    @classmethod
    def _member(cls, key: str, person: dict[str, Any] | None) -> Node:
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=[],
            props=cls._wikidata_props(person),
        )

    @staticmethod
    def _wikidata_props(person: dict[str, Any] | None) -> dict[str, Any]:
        if person is None:
            return {
                "wikidata_id": None,
                "wikidata_name": None,
                "government_functions": None,
            }
        return {
            "wikidata_id": person["id"],
            "wikidata_name": person.get("name"),
            "government_functions": government_functions(person),
        }

    def build_edges(self, raw: Any, normalized: int) -> None:
        """Posts are props of the member, not edges."""
