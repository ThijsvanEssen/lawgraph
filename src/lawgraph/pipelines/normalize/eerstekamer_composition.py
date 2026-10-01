"""Normalize the composition of the Eerste Kamer: its factions, committees and members.

The pages (``ek-composition-html``) show who sits where on the day they were read
(``read_on`` of ``/fracties``): the snapshot. From it:

* a faction ``ek_<slug>`` (``chamber`` ``EK``, labels ``EK``) with its seats and its board,
  and a committee ``ek_<slug>`` (API slug ``ek-<slug>``);
* a member for every person on a faction page: the member of the Tweede Kamer whose date of
  birth is theirs and whose surname ends their name, when exactly one is; else a member of
  their own, ``ek_<slug>``. Its ``ek`` prop holds what the page gives (the name as the Kamer
  writes it, the days served, the place of residence) and its faction;
* ``MEMBER_OF`` from the member to the faction and to every committee it sits in (with the
  role the committee page gives), ``meta.chamber`` ``EK``.

The site gives no start or end of a membership as data, so a period is what was observed:
``observed_from`` the day of the first snapshot that shows it, ``observed_until`` the day
of the first that no longer does. Neither is the day the membership began or ended.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RAW_KIND_EK_COMPOSITION,
    RELATION_MEMBER_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core import eerstekamer_composition as ec
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "eerstekamer-composition"
CHAMBER = "EK"


def _slug(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _url(path: str) -> str:
    return EERSTEKAMER_SITE.rstrip("/") + path


def _surname_ends(name: str, family_name: str | None) -> bool:
    """Whether the name as the Eerste Kamer writes it (``mr. B.O. Dittrich``) ends in the
    surname of the Tweede Kamer (``Dittrich``)."""
    return bool(family_name) and name.casefold().endswith(str(family_name).casefold())


@dataclass
class Snapshot:
    """What the pages show on *day*."""

    day: str
    # the day of the first snapshot the graph holds: nothing before it is known
    since: str = ""
    factions: list[tuple[ec.Listed, ec.Page]] = field(default_factory=list)
    committees: list[tuple[ec.Listed, ec.Page]] = field(default_factory=list)


def snapshot(pages: dict[str, tuple[str, dict[str, Any]]]) -> Snapshot | None:
    """The snapshot of the pages (path -> (html, meta)); None without the list of factions."""
    listing = pages.get(ec.FACTIONS_PATH)
    if listing is None:
        return None
    shot = Snapshot(day=listing[1].get("read_on") or dt.date.today().isoformat())
    for entry in ec.factions(listing[0]):
        if entry.path in pages:
            shot.factions.append((entry, ec.page(pages[entry.path][0])))
    committees = pages.get(ec.COMMITTEES_PATH)
    for entry in ec.committees(committees[0]) if committees else []:
        if entry.path in pages:
            shot.committees.append((entry, ec.page(pages[entry.path][0])))
    return shot


class EerstekamerCompositionNormalizePipeline(NormalizePipelineBase):
    """Factions, committees and members of the Eerste Kamer from its pages."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        # a snapshot is every page, whatever the window
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER, kinds=[RAW_KIND_EK_COMPOSITION], batch_size=20
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> dict[str, Any]:
        pages = {
            str(record["external_id"]): (
                self._payload_text(record) or "",
                self._meta(record),
            )
            for record in raw
        }
        shot = snapshot(pages)
        if shot is None:
            logger.warning("No list of factions of the Eerste Kamer is stored.")
            return {}
        state = normalize_tk.ek_composition(self.store)
        shot.since = min(
            [shot.day]
            + [
                p.get("data_since") or p.get("observed_from") or shot.day
                for row in state["factions"] + state["committees"]
                if (p := row.get("props") or {})
            ]
        )
        members = self._members(shot, state)
        with NodeWriter(self.store) as writer:
            writer.add_all(self._factions(shot, state, members))
            writer.add_all(self._committees(shot, state))
            writer.add_all(members.values())
            writer.add_all(self._departed(shot, state, members))
        logger.info(
            "Eerste Kamer on %s: %d factions, %d committees, %d members.",
            shot.day,
            len(shot.factions),
            len(shot.committees),
            len(members),
        )
        return {"snapshot": shot, "members": members, "state": state}

    # ── members ────────────────────────────────────────────────────────────

    def _members(self, shot: Snapshot, state: dict[str, Any]) -> dict[str, Node]:
        """The member node of every person on a faction page, by the path of their page."""
        known = {
            row["ek"].get("path"): row for row in state["members"] if row.get("ek")
        }
        people = [
            (listed, person)
            for listed, page in shot.factions
            for person in page.members
        ]
        dates = sorted({p.birth_date for _, p in people if p.birth_date})
        born: dict[str, list[dict[str, Any]]] = {}
        for row in normalize_tk.members_born_on(self.store, dates):
            born.setdefault(row["birth_date"], []).append(row)
        nodes: dict[str, Node] = {}
        for listed, person in people:
            stored = known.get(person.path)
            key = stored["key"] if stored else self._match(person, born)
            faction = make_node_key("ek", _slug(listed.path))
            before = (stored or {}).get("ek") or {}
            same = before.get("faction") == faction and not before.get("observed_until")
            ek = {
                "name": person.name,
                "path": person.path,
                "url": _url(person.path),
                "faction": faction,
                "abbreviation": listed.abbreviation,
                "seniority_days": person.seniority_days,
                "residence": person.residence,
                "observed_from": before.get("observed_from") if same else shot.day,
                "observed_until": None,
                "retrieved_on": shot.day,
                "data_since": shot.since,
            }
            props: dict[str, Any] = {"ek": ek}
            if key.startswith("ek_"):
                props.update(name=person.name, birth_date=person.birth_date)
            nodes[person.path] = Node(
                collection=COLLECTION_MEMBERS,
                type=NodeType.MEMBER,
                key=key,
                labels=[CHAMBER],
                props=props,
            )
        return nodes

    @staticmethod
    def _match(person: ec.Person, born: dict[str, list[dict[str, Any]]]) -> str:
        """The key of the one member of the Tweede Kamer born that day whose surname ends
        the name; else a key of their own."""
        found = [
            row
            for row in born.get(person.birth_date or "", [])
            if _surname_ends(person.name, row.get("family_name"))
        ]
        if len(found) == 1:
            return str(found[0]["key"])
        return make_node_key("ek", _slug(person.path))

    @staticmethod
    def _departed(
        shot: Snapshot, state: dict[str, Any], members: dict[str, Node]
    ) -> list[Node]:
        """The members no faction page shows any more: their ``ek`` ends today."""
        return [
            Node(
                collection=COLLECTION_MEMBERS,
                type=NodeType.MEMBER,
                key=row["key"],
                labels=[CHAMBER],
                props={"ek": {**row["ek"], "observed_until": shot.day}},
            )
            for row in state["members"]
            if row["ek"].get("path") not in members
            and not row["ek"].get("observed_until")
        ]

    # ── factions and committees ─────────────────────────────────────────────

    def _factions(
        self, shot: Snapshot, state: dict[str, Any], members: dict[str, Node]
    ) -> list[Node]:
        stored = {row["key"]: row["props"] for row in state["factions"]}
        nodes = []
        for listed, page in shot.factions:
            key = make_node_key("ek", _slug(listed.path))
            nodes.append(
                Node(
                    collection=COLLECTION_FACTIONS,
                    type=NodeType.FACTION,
                    key=key,
                    labels=[CHAMBER],
                    props={
                        **self._observed(stored.get(key), shot),
                        "name": page.title or listed.name,
                        "abbreviation": listed.abbreviation,
                        "seats": listed.seats,
                        "active": True,
                        "board": [
                            {
                                "function": seat.function,
                                "name": seat.name,
                                "member": members[seat.path].key
                                if seat.path in members
                                else None,
                                "since": seat.since,
                            }
                            for seat in page.board
                        ],
                        "url": _url(listed.path),
                    },
                )
            )
        seen = {node.key for node in nodes}
        nodes += [
            Node(
                collection=COLLECTION_FACTIONS,
                type=NodeType.FACTION,
                key=key,
                labels=[CHAMBER],
                props={"observed_until": shot.day, "active": False, "seats": 0},
            )
            for key, props in stored.items()
            if key not in seen and not props.get("observed_until")
        ]
        return nodes

    def _committees(self, shot: Snapshot, state: dict[str, Any]) -> list[Node]:
        stored = {row["key"]: row["props"] for row in state["committees"]}
        nodes = []
        for listed, page in shot.committees:
            slug = _slug(listed.path)
            key = make_node_key("ek", slug)
            nodes.append(
                Node(
                    collection=COLLECTION_COMMITTEES,
                    type=NodeType.COMMITTEE,
                    key=key,
                    labels=[CHAMBER],
                    props={
                        **self._observed(stored.get(key), shot),
                        "name": listed.name,
                        "abbreviation": listed.abbreviation,
                        "slug": "ek-" + slug.replace("_", "-"),
                        "title": page.title,
                        "url": _url(listed.path),
                    },
                )
            )
        seen = {node.key for node in nodes}
        nodes += [
            Node(
                collection=COLLECTION_COMMITTEES,
                type=NodeType.COMMITTEE,
                key=key,
                labels=[CHAMBER],
                props={"observed_until": shot.day},
            )
            for key, props in stored.items()
            if key not in seen and not props.get("observed_until")
        ]
        return nodes

    @staticmethod
    def _observed(stored: dict[str, Any] | None, shot: Snapshot) -> dict[str, Any]:
        """``chamber``, ``observed_from`` (kept while it stays observed), ``observed_until``
        (none: it is seen today), ``retrieved_on`` (the day of the snapshot) and
        ``data_since`` (of the first)."""
        open_ = stored is not None and not stored.get("observed_until")
        return {
            "chamber": CHAMBER,
            "observed_from": stored["observed_from"] if open_ and stored else shot.day,
            "observed_until": None,
            "retrieved_on": shot.day,
            "data_since": shot.since,
        }

    # ── edges ──────────────────────────────────────────────────────────────

    def build_edges(self, raw: Any, normalized: dict[str, Any]) -> None:
        """``MEMBER_OF`` from each member to its faction and committees, as observed; an
        edge the snapshot no longer shows ends on its day."""
        shot: Snapshot | None = normalized.get("snapshot")
        if shot is None:
            return
        members: dict[str, Node] = normalized["members"]
        stored = {
            (e["from"], e["to"]): e.get("meta") or {}
            for e in normalized["state"]["edges"]
        }
        wanted: dict[tuple[str, str], dict[str, Any]] = {}
        for listed, page in shot.factions:
            target = f"{COLLECTION_FACTIONS}/{make_node_key('ek', _slug(listed.path))}"
            for person in page.members:
                wanted[(members[person.path].node_id or "", target)] = {
                    "seniority_days": person.seniority_days
                }
        for listed, page in shot.committees:
            target = (
                f"{COLLECTION_COMMITTEES}/{make_node_key('ek', _slug(listed.path))}"
            )
            for person in page.members:
                if person.path in members:
                    wanted[(members[person.path].node_id or "", target)] = {
                        "role": person.role
                    }
        writer = EdgeWriter(self.store, what="MEMBER_OF edges of the Eerste Kamer")
        for (source, target), extra in wanted.items():
            before = stored.get((source, target)) or {}
            open_ = bool(before) and not before.get("observed_until")
            writer.add(
                source,
                target,
                RELATION_MEMBER_OF,
                source=EDGE_SOURCE,
                meta={
                    "chamber": CHAMBER,
                    "observed_from": before.get("observed_from") if open_ else shot.day,
                    "observed_until": None,
                    **extra,
                },
            )
        for (source, target), meta in stored.items():
            if (source, target) not in wanted and not meta.get("observed_until"):
                writer.add(
                    source,
                    target,
                    RELATION_MEMBER_OF,
                    source=EDGE_SOURCE,
                    meta={**meta, "observed_until": shot.day},
                )
        writer.flush()
