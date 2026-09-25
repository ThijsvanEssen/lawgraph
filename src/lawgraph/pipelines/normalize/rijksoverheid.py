"""Normalize pipeline for Rijksoverheid: the cabinets, who held which post in them, and when.

Every cabinet becomes a node of ``cabinets`` (``core.cabinet_sources``): those since 1945
from their Rijksoverheid page, with their phases, parties and prime minister; those before
from the stored Wikidata records, with only their name and period. The collection is derived
in full: a cabinet no source names any more is removed.

A holder of a post (``Drs. S.Th.M. (Sophie) Hermans (VVD)``) is matched to one Tweede Kamer
person (``core.government``): a member of parliament by surname, initials and age, told
apart by the faction of their party where two fit; a minister who never sat in parliament
(a TK person without name or date) by the papers they signed. The member gets
``government_functions`` (their posts, oldest first) and ``government_name`` (the name as
Rijksoverheid writes it). A holder who matches nobody becomes a member of their own, keyed by
initials and surname, labelled ``Rijksoverheid``; one that is no longer needed is removed,
and a member that no longer holds a post loses both props. Every member gets an edge
``SERVED_IN`` to every cabinet they held a post in, with those posts; the edges are derived
in full.

A holder is looked up once per initials, surname and party: a party is part of who someone
is on these pages (``dr. W. Drees (PvdA)`` in 1948 is not ``dr. W. Drees (DS'70)`` in
1971), and one person under two parties matches one member twice.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_MEMBERS,
    LABEL_RIJKSOVERHEID,
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_WIKIDATA_CABINET,
    RELATION_SERVED_IN,
    SOURCE_RIJKSOVERHEID,
    SOURCE_WIKIDATA,
)
from lawgraph.core.cabinet_posts import SEAT_PRIME_MINISTER
from lawgraph.core.cabinet_sources import NO_PARTY, build_cabinets
from lawgraph.core.cabinets import faction_of
from lawgraph.core.government import match_holder, match_signatory
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.raw_records import meta
from lawgraph.core.rijksoverheid import parse_page, split_name
from lawgraph.db.edges import EdgeWriter, make_edge_doc
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

# What a post keeps on a member and on its SERVED_IN edge.
POST_FIELDS = (
    "cabinet_key",
    "cabinet",
    "function",
    "also_named",
    "post",
    "ministry",
    "seat",
    "portfolio",
    "from_date",
    "to_date",
    "from_date_source",
    "to_date_source",
    "corrected",
    "acting",
    "acting_basis",
    "party",
    "overlaps_with",
    "absent",
    "name",
    "source",
)


def holder_name(name: str) -> str:
    """``S.Th.M. Hermans`` of ``Drs. S.Th.M. (Sophie) Hermans``."""
    parts = split_name(name)
    return f"{parts['initials']} {parts['surname']}".strip()


class RijksoverheidNormalizePipeline(NormalizePipelineBase):
    """Write the cabinets and the posts held in them onto the members."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)
        # (member key, cabinet key) -> the posts held in it, for ``build_edges``
        self._served: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        yield from self._iter_raw_sources(
            source=SOURCE_RIJKSOVERHEID,
            kinds=[RAW_KIND_RIJKSOVERHEID_CABINET],
            batch_size=50,
        )
        yield from self._iter_raw_sources(
            source=SOURCE_WIKIDATA, kinds=[RAW_KIND_WIKIDATA_CABINET], batch_size=500
        )

    def normalize_nodes(
        self, raw: Iterator[dict[str, Any]], result: PipelineResult
    ) -> int:
        pages, wikidata = [], []
        for record in raw:
            if record.get("kind") == RAW_KIND_WIKIDATA_CABINET:
                item = self._payload_json(record)
                if isinstance(item, dict) and item.get("id"):
                    wikidata.append(item)
                continue
            html = self._payload_text(record)
            if not html:
                result.skipped += 1
                continue
            about = meta(record)
            pages.append(
                {
                    "slug": record.get("external_id"),
                    "url": about.get("url"),
                    "read_on": about.get("read_on"),
                    "page": parse_page(html),
                }
            )
        factions = list(normalize_queries.faction_names(self.store))
        cabinets = build_cabinets(
            pages, wikidata, lambda text: party_of(text, factions)
        )
        member_of, own = self._members_of(cabinets)
        posts = self._posts_by_member(cabinets, member_of)
        nodes = [self._cabinet(c, member_of) for c in cabinets]
        nodes += [self._member(key, held, own) for key, held in posts.items()]
        cleared = [
            self._cleared(key)
            for key in normalize_queries.government_members(self.store)
            if key not in posts
        ]
        self._upsert_nodes([*nodes, *cleared])
        removed = self._remove_stale(own, {c["key"] for c in cabinets})
        self._served = self._by_cabinet(posts)
        logger.info(
            "Rijksoverheid: %d cabinets (%d with posts), %d posts of %d members "
            "(%d of their own), %d members cleared, %d nodes removed.",
            len(cabinets),
            sum(1 for c in cabinets if c["posts"]),
            sum(len(held) for held in posts.values()),
            len(posts),
            len(own),
            len(cleared),
            removed,
        )
        return len(nodes)

    # ── Who is who ───────────────────────────────────────────────────────────

    def _members_of(
        self, cabinets: list[dict[str, Any]]
    ) -> tuple[dict[str, str], set[str]]:
        """``<person key>|<party>`` of every holder -> their member key; and the keys of
        the members of their own."""
        holders = holder_records(cabinets)
        members = list(normalize_queries.member_identities(self.store))
        claims: dict[str, list[str]] = defaultdict(list)
        for key, holder in holders.items():
            member = match_holder(holder, members)
            if member is not None:
                claims[member].append(key)
        member_of = _one_person_each(claims, holders)
        rest = [h for k, h in holders.items() if k not in member_of]
        member_of.update(self._match_signatories(rest))
        own: set[str] = set()
        for key, holder in holders.items():
            if key not in member_of:
                member_of[key] = make_node_key(SOURCE_RIJKSOVERHEID, holder["person"])
                own.add(member_of[key])
                logger.info(
                    "Rijksoverheid: no Tweede Kamer person for %s (%s).",
                    holder["name"],
                    holder["id"].partition("|")[2] or "no party",
                )
        logger.info(
            "Rijksoverheid: %d holders (initials, surname and party), %d matched to a "
            "Tweede Kamer person; %d members of their own.",
            len(holders),
            len(holders) - sum(1 for k in holders if member_of[k] in own),
            len(own),
        )
        return member_of, own

    def _match_signatories(self, holders: list[dict[str, Any]]) -> dict[str, str]:
        """Holder -> member key, for the members without a name of their own, by the
        papers they signed as a minister or state secretary."""
        signatures: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in normalize_queries.government_signatures(self.store):
            signatures[row["key"]].append(row)
        people = [
            {"id": h["id"], "name": h["name"], "posts": h["posts"]} for h in holders
        ]
        claims: dict[str, list[str]] = defaultdict(list)
        for member, signed in signatures.items():
            holder = match_signatory(signed, people)
            if holder is not None:
                claims[member].append(holder)
        return _one_person_each(claims, {h["id"]: h for h in holders})

    # ── Nodes ────────────────────────────────────────────────────────────────

    def _posts_by_member(
        self, cabinets: list[dict[str, Any]], member_of: dict[str, str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Member key -> their posts, oldest first, as stored."""
        held: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cabinet in cabinets:
            by_person = {p["person"]: member_of[holder_id(p)] for p in cabinet["posts"]}
            for post in cabinet["posts"]:
                stored = {k: post.get(k) for k in POST_FIELDS}
                stored["overlaps_with"] = sorted(
                    {by_person[p] for p in post["overlaps_with"] if p in by_person}
                )
                held[member_of[holder_id(post)]].append(stored)
        for posts in held.values():
            posts.sort(key=lambda p: (p["from_date"] or "", p["seat"] or ""))
        return held

    @staticmethod
    def _cabinet(cabinet: dict[str, Any], member_of: dict[str, str]) -> Node:
        prime = sorted(
            (p["from_date"], member_of[holder_id(p)])
            for p in cabinet["posts"]
            if p["seat"] == SEAT_PRIME_MINISTER
        )
        return Node(
            collection=COLLECTION_CABINETS,
            type=NodeType.CABINET,
            key=cabinet["key"],
            labels=[],
            props={
                "name": cabinet["name"],
                "display_name": cabinet["name"],
                "wikidata_id": cabinet.get("wikidata_id"),
                "from_date": cabinet["from_date"],
                "from_date_precision": cabinet.get("from_date_precision"),
                "to_date": cabinet["to_date"],
                "to_date_precision": cabinet.get("to_date_precision"),
                "prime_minister": prime[0][1] if prime else None,
                "previous": cabinet["previous"],
                "parties": cabinet["parties"],
                "factions": [p["faction"] for p in cabinet["parties"] if p["faction"]],
                "phases": cabinet["phases"],
                "demissionary_from": cabinet["demissionary_from"],
                "origin": cabinet["source"],
            },
        )

    @staticmethod
    def _member(key: str, posts: list[dict[str, Any]], own: set[str]) -> Node:
        name = holder_name(posts[-1]["name"] or "")
        props: dict[str, Any] = {
            "government_name": name,
            "government_functions": posts,
        }
        if key in own:
            props.update({"external_id": key, "name": name, "display_name": name})
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=[LABEL_RIJKSOVERHEID] if key in own else [],
            props=props,
        )

    @staticmethod
    def _cleared(key: str) -> Node:
        return Node(
            collection=COLLECTION_MEMBERS,
            type=NodeType.MEMBER,
            key=key,
            labels=[],
            props={"government_name": None, "government_functions": None},
        )

    def _remove_stale(self, own: set[str], cabinets: set[str]) -> int:
        """Remove the members of their own no holder needs, and the cabinets no source
        names any more."""
        gone = [
            key
            for key in normalize_queries.labelled_members(
                self.store, LABEL_RIJKSOVERHEID
            )
            if key not in own
        ]
        removed = normalize_queries.remove_members(self.store, gone) if gone else 0
        return removed + normalize_queries.remove_nodes_except(
            self.store, COLLECTION_CABINETS, sorted(cabinets)
        )

    @staticmethod
    def _by_cabinet(
        posts: dict[str, list[dict[str, Any]]],
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        served: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for member, held in posts.items():
            for post in held:
                served[(member, post["cabinet_key"])].append(post)
        return served

    def build_edges(self, raw: Any, normalized: int) -> None:
        """An edge ``SERVED_IN`` from every member to every cabinet they held a post in;
        the edges no post supports any more are removed."""
        docs = [
            make_edge_doc(
                f"{COLLECTION_MEMBERS}/{member}",
                f"{COLLECTION_CABINETS}/{cabinet}",
                RELATION_SERVED_IN,
                source=SOURCE_RIJKSOVERHEID,
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
            "Rijksoverheid: %d members served in a cabinet (%d edges removed).",
            len(docs),
            removed,
        )


# ── Holders ──────────────────────────────────────────────────────────────────


def party_of(text: str | None, factions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """``{short, faction}`` of a party as Rijksoverheid writes it; the faction of the
    whole name, else of its last part that has one (``SDAP/PvdA``: the PvdA)."""
    if not text:
        return None
    if text == NO_PARTY:
        return {"short": NO_PARTY, "faction": None}
    faction = faction_of({"name": text, "short": text}, factions)
    for part in reversed(re.split(r"\s*/\s*", text)):
        if faction:
            break
        faction = faction_of({"name": part, "short": part}, factions)
    return {"short": text, "faction": faction}


def holder_id(post: dict[str, Any]) -> str:
    """``<person key>|<party>``: one holder as the pipeline looks them up."""
    party = post.get("party") or {}
    return f"{post['person']}|{party.get('short') or ''}"


def holder_records(cabinets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Holder id -> ``{id, person, name, surname, letters, days, factions, posts}``: what
    ``match_holder`` and ``match_signatory`` read."""
    holders: dict[str, dict[str, Any]] = {}
    for cabinet in cabinets:
        for post in cabinet["posts"]:
            key = holder_id(post)
            parts = split_name(post["name"])
            holder = holders.setdefault(
                key,
                {
                    "id": key,
                    "person": post["person"],
                    "name": post["name"],
                    "surname": parts["surname"],
                    "letters": parts["letters"],
                    "days": [],
                    "factions": [],
                    "posts": [],
                },
            )
            holder["days"].append(post["from_date"])
            faction = (post.get("party") or {}).get("faction")
            if faction and faction not in holder["factions"]:
                holder["factions"].append(faction)
            holder["posts"].append(
                {
                    "function": post["function"],
                    "from_date": post["from_date"],
                    "to_date": post["to_date"],
                }
            )
    return holders


def _one_person(holders: list[dict[str, Any]]) -> bool:
    """Whether *holders* are one person written in more ways: a surname part of the
    others, and initials of which one begins the other (``M. Paul``, ``M.L.J. Paul``)."""
    surnames = sorted(
        ({*h["person"].split(" ")[1:]} for h in holders), key=len
    )  # word sets: ``Bijleveld`` is part of ``Bijleveld-Schouten``
    letters = sorted({h["letters"] for h in holders}, key=len)
    return all(surnames[0] <= words for words in surnames) and all(
        longer.startswith(shorter)
        for shorter, longer in zip(letters, letters[1:], strict=False)
    )


def _one_person_each(
    claims: dict[str, list[str]], holders: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Holder id -> member key, where the holders that claim a member are one person
    (``_one_person``; a party apart); a member two people claim is logged and kept by
    neither."""
    found: dict[str, str] = {}
    for member, keys in claims.items():
        if not _one_person([holders[k] for k in keys]):
            logger.warning(
                "Rijksoverheid: member %s is claimed by %s; none is kept.",
                member,
                ", ".join(sorted({holders[k]["person"] for k in keys})),
            )
            continue
        found.update(dict.fromkeys(keys, member))
    return found
