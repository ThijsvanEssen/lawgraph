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

Every cabinet becomes a node of ``cabinets`` (``core.cabinets``): its name, dates, prime
minister (a member key), the cabinet before it and its parties, with the faction of each
where a faction bears its name. Every post gets its normalised ``post`` and ``ministry``
(``core.ministries``) and the key of its cabinet, and each member an edge ``SERVED_IN`` to
every cabinet they held a post in, with those posts. The edges are derived in full on every
run: an edge no post supports any more is removed.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_MEMBERS,
    LABEL_WIKIDATA,
    RAW_KIND_WIKIDATA_CABINET,
    RAW_KIND_WIKIDATA_CABINET_POSTS,
    RELATION_SERVED_IN,
    SOURCE_WIKIDATA,
)
from lawgraph.core.cabinets import (
    cabinet_key,
    cabinet_name,
    cabinet_parties,
    faction_of,
    prime_minister,
)
from lawgraph.core.government import (
    PRECISION_DAY,
    government_functions,
    match_member,
    match_signatory,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.ministries import classify_function
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db.edges import EdgeWriter, make_edge_doc
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
        # (member key, cabinet key) -> the posts held in it, for ``build_edges``
        self._served: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_WIKIDATA,
            kinds=[RAW_KIND_WIKIDATA_CABINET_POSTS, RAW_KIND_WIKIDATA_CABINET],
            batch_size=500,
        )

    def normalize_nodes(
        self, raw: Iterator[dict[str, Any]], result: PipelineResult
    ) -> int:
        people: dict[str, dict[str, Any]] = {}
        cabinets: dict[str, dict[str, Any]] = {}
        for record in raw:
            item = self._payload_json(record)
            if not isinstance(item, dict) or not item.get("id"):
                result.skipped += 1
                continue
            into = (
                cabinets if record.get("kind") == RAW_KIND_WIKIDATA_CABINET else people
            )
            into[item["id"]] = item

        members = list(normalize_queries.member_identities(self.store))
        by_member = self._match_members(people, members)
        by_signatures = self._match_signatories(
            [p for p in people.values() if p["id"] not in by_member.values()]
        )
        matched = {**by_member, **by_signatures}  # member key -> Q-id
        own = [p for qid, p in people.items() if qid not in matched.values()]

        member_of = {qid: key for key, qid in matched.items()}
        member_of.update({p["id"]: self._own_key(p["id"]) for p in own})
        keys = self._cabinet_keys(cabinets)
        cabinet_nodes = self._cabinets(cabinets, keys, people, member_of)

        nodes = [self._member(key, people[qid], keys) for key, qid in matched.items()]
        cleared = [
            self._member(m["key"], None, keys)
            for m in members
            if m.get("wikidata_id") and m["key"] not in matched
        ]
        self._upsert_nodes(
            [
                *cabinet_nodes,
                *nodes,
                *cleared,
                *(self._own_member(p, keys) for p in own),
            ]
        )
        self._served = self._posts_by_cabinet(people, member_of, keys)
        removed = self._remove_superseded({self._own_key(p["id"]) for p in own})
        logger.info(
            "Wikidata: %d people matched to a member of parliament, %d to a minister "
            "by their signatures, %d members of their own (%d removed: now matched); "
            "%d members cleared; %d cabinets.",
            len(by_member),
            len(by_signatures),
            len(own),
            removed,
            len(cleared),
            len(cabinet_nodes),
        )
        return len(nodes) + len(own)

    @staticmethod
    def _cabinet_keys(cabinets: dict[str, dict[str, Any]]) -> dict[str, str]:
        """Q-id -> node key of every cabinet; a key two cabinets would share gets the
        Q-id of the later one."""
        keys: dict[str, str] = {}
        taken: set[str] = set()
        for qid, cabinet in sorted(
            cabinets.items(), key=lambda c: (c[1].get("from_date") or "", c[0])
        ):
            key = cabinet_key(cabinet_name(cabinet.get("name"))) or qid.lower()
            if key in taken:
                key = f"{key}_{qid.lower()}"
            taken.add(key)
            keys[qid] = key
        return keys

    def _cabinets(
        self,
        cabinets: dict[str, dict[str, Any]],
        keys: dict[str, str],
        people: dict[str, dict[str, Any]],
        member_of: dict[str, str],
    ) -> list[Node]:
        factions = list(normalize_queries.faction_names(self.store))
        nodes = []
        unmatched: set[str] = set()
        for qid, cabinet in cabinets.items():
            parties = [
                {
                    "name": party["name"],
                    "short": party["short"],
                    "wikidata_id": party["id"],
                    "faction": faction_of(party, factions),
                }
                for party in cabinet_parties(qid, people.values())
            ]
            unmatched.update(p["name"] or "" for p in parties if not p["faction"])
            head = prime_minister(cabinet, people.values())
            previous = [keys[q] for q in cabinet.get("previous") or [] if q in keys]
            name = cabinet_name(cabinet.get("name")) or qid
            nodes.append(
                Node(
                    collection=COLLECTION_CABINETS,
                    type=NodeType.CABINET,
                    key=keys[qid],
                    labels=[LABEL_WIKIDATA],
                    props={
                        "name": name,
                        "display_name": name,
                        "wikidata_id": qid,
                        "from_date": cabinet.get("from_date"),
                        "to_date": cabinet.get("to_date"),
                        "prime_minister": member_of.get(head or ""),
                        "previous": previous[0] if previous else None,
                        "parties": parties,
                        "factions": [p["faction"] for p in parties if p["faction"]],
                    },
                )
            )
        logger.info(
            "Wikidata: %d parties of cabinets have no faction of their name: %s.",
            len(unmatched),
            ", ".join(sorted(unmatched)),
        )
        return nodes

    @staticmethod
    def _posts_by_cabinet(
        people: dict[str, dict[str, Any]],
        member_of: dict[str, str],
        keys: dict[str, str],
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        served: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for qid, person in people.items():
            member = member_of.get(qid)
            if member is None:
                continue
            for post in government_posts(person, keys):
                if post["cabinet_key"]:
                    served[(member, post["cabinet_key"])].append(
                        {
                            k: post[k]
                            for k in (
                                "function",
                                "post",
                                "ministry",
                                "from_date",
                                "to_date",
                            )
                        }
                    )
        return served

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
    def _own_member(cls, person: dict[str, Any], keys: dict[str, str]) -> Node:
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
                **cls._wikidata_props(person, keys),
            },
        )

    @classmethod
    def _member(
        cls, key: str, person: dict[str, Any] | None, keys: dict[str, str]
    ) -> Node:
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=[],
            props=cls._wikidata_props(person, keys),
        )

    @staticmethod
    def _wikidata_props(
        person: dict[str, Any] | None, keys: dict[str, str]
    ) -> dict[str, Any]:
        if person is None:
            return {
                "wikidata_id": None,
                "wikidata_name": None,
                "government_functions": None,
            }
        return {
            "wikidata_id": person["id"],
            "wikidata_name": person.get("name"),
            "government_functions": government_posts(person, keys),
        }

    def build_edges(self, raw: Any, normalized: int) -> None:
        """An edge ``SERVED_IN`` from every member to every cabinet they held a post in;
        the edges no post supports any more are removed."""
        docs = [
            make_edge_doc(
                f"{COLLECTION_MEMBERS}/{member}",
                f"{COLLECTION_CABINETS}/{cabinet}",
                RELATION_SERVED_IN,
                source=SOURCE_WIKIDATA,
                meta={"posts": posts},
            )
            for (member, cabinet), posts in self._served.items()
        ]
        with EdgeWriter(self.store, what=None) as writer:
            for doc in docs:
                writer.add_doc(doc)
        removed = normalize_queries.remove_edges_except(
            self.store, RELATION_SERVED_IN, [doc["_key"] for doc in docs]
        )
        logger.info(
            "Wikidata: %d members served in a cabinet (%d edges removed).",
            len(docs),
            removed,
        )


def government_posts(
    person: dict[str, Any], keys: dict[str, str]
) -> list[dict[str, Any]]:
    """The posts of *person* as a member stores them (``government_functions``), each with
    its normalised ``post`` and ``ministry`` on the day it began, and its ``cabinet_key``."""
    posts = []
    for post in government_functions(person):
        kind, ministry = classify_function(post["function"], on=post["from_date"])
        posts.append(
            {
                **post,
                "cabinet_key": keys.get(post.get("cabinet_id") or ""),
                "post": kind,
                "ministry": ministry,
            }
        )
    return posts
