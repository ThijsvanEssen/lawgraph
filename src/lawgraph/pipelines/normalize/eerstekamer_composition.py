"""Normalize the composition of the Eerste Kamer: its factions, committees and members.

The pages (``ek-composition-html``) are stored once per day their content changed
(``retrieve eerstekamer-composition``). The composition on such a day, the snapshot, is the
newest version of every page read on or before it (``ek_composition.versions_by_day``). From
each snapshot:

* a faction ``ek_<slug>`` (``chamber`` ``EK``, labels ``EK``) with its seats and its board,
  and a committee ``ek_<slug>`` (API slug ``ek-<slug>``);
* a member for every person on a faction page: the member of the Tweede Kamer whose date of
  birth is theirs and whose surname ends their name, when exactly one is
  (``ek_persons.match_member``, as ``normalize eerstekamer-persons`` matches a page); else a
  member of their own, ``ek_<slug>``. Its ``ek`` prop holds what the page gives (the name as
  the Kamer writes it, the days served, the place of residence), its faction and its seat in
  the hall (``seat``: ``block``, ``row``, ``column`` as ``/wie_zit_waar`` draws it; null when
  the plan places them nowhere);
* ``MEMBER_OF`` from the member to the faction and to every committee it sits in (with the
  role the committee page gives), ``meta.chamber`` ``EK``.

The site gives no start or end of a membership as data, so a period is what was observed:
``observed_from`` the day of the first snapshot that shows it, ``observed_until`` the day
of the first that no longer does. Neither is the day the membership began or ended. The
snapshots are walked in order from the composition the record ``ek-composition-observed``
holds (``retrieve eerstekamer-composition-observed``: the periods observed before the
versions were kept), or from nothing; the versions that record covers are not walked again.
The result depends on the raw records only: a rebuild gives the same periods.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_COMMITTEES,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RAW_KIND_EERSTEKAMER_COMPOSITION,
    RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED,
    RELATION_MEMBER_OF,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_composition as ec
from lawgraph.core import ek_persons
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.official_urls import ek_url
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.normalize._member_slugs import assign_member_slugs
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records
from lawgraph.sources.addresses import edge_source

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)

# the props of a faction and a committee this pipeline writes: all that is taken of them
# from the composition ``ek-composition-observed`` holds
_OBSERVED_PROPS = ("chamber", "observed_from", "observed_until")
_READ_PROPS = ("retrieved_on", "data_since")
FACTION_PROPS = (
    *_OBSERVED_PROPS,
    *_READ_PROPS,
    *("name", "abbreviation", "seats", "active", "board", "url"),
)
COMMITTEE_PROPS = (
    *_OBSERVED_PROPS,
    *_READ_PROPS,
    *("name", "abbreviation", "slug", "title", "url"),
)


def _slug(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _seat(seat: ec.HallSeat | None) -> dict[str, Any] | None:
    """Where a member sits: ``{block, row, column}`` of the plan, None for nowhere."""
    if seat is None:
        return None
    return {"block": seat.block, "row": seat.row, "column": seat.column}


@dataclass
class Snapshot:
    """What the pages show on *day*."""

    day: str
    factions: list[tuple[ec.Listed, ec.Page]] = field(default_factory=list)
    committees: list[tuple[ec.Listed, ec.Page]] = field(default_factory=list)
    # the seat of each member in the hall, by the path of their page
    seats: dict[str, ec.HallSeat] = field(default_factory=dict)
    # the paths of the listed factions and committees whose page is not stored
    missing: list[str] = field(default_factory=list)


def snapshot(pages: dict[str, str], day: str) -> Snapshot | None:
    """The snapshot of the pages (path -> html) on *day*; None without the list of
    factions."""
    listing = pages.get(ec.FACTIONS_PATH)
    if listing is None:
        return None
    shot = Snapshot(day=day)
    for entry in ec.factions(listing):
        if entry.path in pages:
            shot.factions.append((entry, ec.page(pages[entry.path])))
        else:
            shot.missing.append(entry.path)
    committees = pages.get(ec.COMMITTEES_PATH)
    for entry in ec.committees(committees) if committees else []:
        if entry.path in pages:
            shot.committees.append((entry, ec.page(pages[entry.path])))
        else:
            shot.missing.append(entry.path)
    shot.seats = {
        seat.person: seat
        for seat in ec.hall(pages.get(ec.HALL_PATH) or "")
        if seat.person
    }
    return shot


@dataclass
class State:
    """The composition as observed up to a snapshot: what the graph gets."""

    # the day of the first snapshot: nothing before it is known
    since: str = ""
    # props by key
    factions: dict[str, dict[str, Any]] = field(default_factory=dict)
    committees: dict[str, dict[str, Any]] = field(default_factory=dict)
    # the member of every person ever on a faction page, by the path of their page
    members: dict[str, Node] = field(default_factory=dict)
    # MEMBER_OF: meta by (member id, faction or committee id)
    edges: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


def _member(key: str, props: dict[str, Any]) -> Node:
    return Node(
        collection=COLLECTION_MEMBERS, key=key, labels=[CHAMBER_EK], props=props
    )


def observed_state(record: dict[str, Any]) -> tuple[State, set[str]]:
    """The composition an ``ek-composition-observed`` record holds, and the external ids
    of the versions it covers."""
    held = payload_json(record)
    state = State()
    for collection, kept, names in (
        ("factions", state.factions, FACTION_PROPS),
        ("committees", state.committees, COMMITTEE_PROPS),
    ):
        for row in held.get(collection) or []:
            props = row.get("props") or {}
            kept[row["key"]] = {k: props[k] for k in names if k in props}
    for row in held.get("members") or []:
        ek = row.get("ek") or {}
        member: dict[str, Any] = {"ek": ek}
        if str(row["key"]).startswith("ek_"):
            member.update(name=row.get("name"), birth_date=row.get("birth_date"))
        state.members[str(ek.get("path"))] = _member(row["key"], member)
    for edge in held.get("edges") or []:
        state.edges[(edge["from"], edge["to"])] = edge.get("meta") or {}
    state.since = min(
        (
            str(p.get("data_since") or p.get("observed_from"))
            for p in [*state.factions.values(), *state.committees.values()]
            if p.get("data_since") or p.get("observed_from")
        ),
        default="",
    )
    return state, {str(one) for one in held.get("covers") or []}


class EerstekamerCompositionNormalizePipeline(NormalizePipelineBase[Records]):
    """Factions, committees and members of the Eerste Kamer from its pages."""

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Records:
        # every snapshot is walked again, whatever the window
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[
                RAW_KIND_EERSTEKAMER_COMPOSITION,
                RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED,
            ],
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The factions, committees and members, then their MEMBER_OF edges."""
        state = self.observe(raw)
        if state is not None:
            self._write(state)

    def observe(self, raw: Records) -> State | None:
        """The composition the records give: their snapshots walked in order; None
        without any snapshot or observed composition."""
        records = list(raw)
        held = [
            r
            for r in records
            if r.get("kind") == RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED
        ]
        versions = [
            r
            for r in records
            if r.get("kind") != RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED
        ]
        state, covered = observed_state(held[-1]) if held else (State(), set())
        shots = self._snapshots(versions, covered)
        if not shots and not state.factions:
            self.progress.skip("no list of factions", ec.FACTIONS_PATH, len(records))
            return None
        for path in shots[-1].missing if shots else []:
            self.progress.skip("listed page not stored", path)
        born = self._born(shots)
        for shot in shots:
            self._step(state, shot, born)
        _read_on(state, _last_read(versions))
        logger.info(
            "Eerste Kamer: %d snapshots walked; %d factions, %d committees, %d members.",
            len(shots),
            len(state.factions),
            len(state.committees),
            len(state.members),
        )
        return state

    @staticmethod
    def _snapshots(versions: list[dict[str, Any]], covered: set[str]) -> list[Snapshot]:
        """The snapshot of every day a version was read that *covered* does not hold."""
        shots = []
        for day, read, newest in ec.versions_by_day(versions):
            if all(str(r.get("external_id")) in covered for r in read):
                continue
            pages = {path: payload_text(r) or "" for path, r in newest.items()}
            shot = snapshot(pages, day)
            if shot is not None:
                shots.append(shot)
        return shots

    def _born(self, shots: list[Snapshot]) -> list[dict[str, Any]]:
        """The members of the Tweede Kamer born on a day a person of *shots* was."""
        dates = sorted(
            {
                person.birth_date
                for shot in shots
                for _, page in shot.factions
                for person in page.members
                if person.birth_date
            }
        )
        return list(normalize_tk.members_born_on(self.store, dates)) if dates else []

    def _step(self, state: State, shot: Snapshot, born: list[dict[str, Any]]) -> None:
        """*state* after *shot*."""
        state.since = min(state.since or shot.day, shot.day)
        members = self._members(state, shot, born)
        self._factions(state, shot, members)
        self._committees(state, shot)
        self._link(state, shot, members)

    # ── members ────────────────────────────────────────────────────────────

    def _members(
        self, state: State, shot: Snapshot, born: list[dict[str, Any]]
    ) -> dict[str, Node]:
        """The member of every person on a faction page, by the path of their page; the
        members no faction page shows any more end on the day of *shot*."""
        nodes: dict[str, Node] = {}
        for listed, page in shot.factions:
            for person in page.members:
                stored = state.members.get(person.path)
                key = stored.key if stored and stored.key else self._match(person, born)
                faction = make_node_key("ek", _slug(listed.path))
                before = (stored.props.get("ek") if stored else None) or {}
                same = before.get("faction") == faction and not before.get(
                    "observed_until"
                )
                ek = {
                    "name": person.name,
                    "path": person.path,
                    "url": ek_url(person.path),
                    "faction": faction,
                    "abbreviation": listed.abbreviation,
                    "seniority_days": person.seniority_days,
                    "residence": person.residence,
                    "seat": _seat(shot.seats.get(person.path)),
                    "observed_from": before.get("observed_from") if same else shot.day,
                    "observed_until": None,
                    "retrieved_on": shot.day,
                    "data_since": state.since,
                }
                props: dict[str, Any] = {"ek": ek}
                if key.startswith("ek_"):
                    props.update(name=person.name, birth_date=person.birth_date)
                nodes[person.path] = _member(key, props)
        for path, node in list(state.members.items()):
            ek = node.props.get("ek") or {}
            if path not in nodes and not ek.get("observed_until"):
                ended = {**ek, "observed_until": shot.day}
                state.members[path] = _member(
                    node.key or "", {**node.props, "ek": ended}
                )
        state.members.update(nodes)
        return nodes

    @staticmethod
    def _match(person: ec.Person, born: list[dict[str, Any]]) -> str:
        """The key of the member of the Tweede Kamer the person is
        (``ek_persons.match_member``); else a key of their own."""
        return ek_persons.match_member(
            person.name, person.birth_date, born
        ) or make_node_key("ek", _slug(person.path))

    # ── factions and committees ─────────────────────────────────────────────

    @staticmethod
    def _factions(state: State, shot: Snapshot, members: dict[str, Node]) -> None:
        seen = set()
        for listed, page in shot.factions:
            key = make_node_key("ek", _slug(listed.path))
            seen.add(key)
            state.factions[key] = {
                **_observed(state.factions.get(key), shot, state.since),
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
                "url": ek_url(listed.path),
            }
        for key, props in list(state.factions.items()):
            if key not in seen and not props.get("observed_until"):
                state.factions[key] = {
                    **props,
                    "observed_until": shot.day,
                    "active": False,
                    "seats": 0,
                }

    @staticmethod
    def _committees(state: State, shot: Snapshot) -> None:
        seen = set()
        for listed, page in shot.committees:
            slug = _slug(listed.path)
            key = make_node_key("ek", slug)
            seen.add(key)
            state.committees[key] = {
                **_observed(state.committees.get(key), shot, state.since),
                "name": listed.name,
                "abbreviation": listed.abbreviation,
                "slug": "ek-" + slug.replace("_", "-"),
                "title": page.title,
                "url": ek_url(listed.path),
            }
        for key, props in list(state.committees.items()):
            if key not in seen and not props.get("observed_until"):
                state.committees[key] = {**props, "observed_until": shot.day}

    # ── edges ──────────────────────────────────────────────────────────────

    @staticmethod
    def _link(state: State, shot: Snapshot, members: dict[str, Node]) -> None:
        """``MEMBER_OF`` from each member to its faction and committees, as observed; an
        edge the snapshot no longer shows ends on its day."""
        wanted: dict[tuple[str, str], dict[str, Any]] = {}
        for listed, page in shot.factions:
            target = node_id(
                COLLECTION_FACTIONS, make_node_key("ek", _slug(listed.path))
            )
            for person in page.members:
                wanted[(members[person.path].node_id or "", target)] = {
                    "seniority_days": person.seniority_days
                }
        for listed, page in shot.committees:
            target = node_id(
                COLLECTION_COMMITTEES, make_node_key("ek", _slug(listed.path))
            )
            for person in page.members:
                if person.path in members:
                    wanted[(members[person.path].node_id or "", target)] = {
                        "role": person.role
                    }
        for pair, extra in wanted.items():
            before = state.edges.get(pair) or {}
            open_ = bool(before) and not before.get("observed_until")
            state.edges[pair] = {
                "chamber": CHAMBER_EK,
                "observed_from": before.get("observed_from") if open_ else shot.day,
                "observed_until": None,
                **extra,
            }
        for pair, edge_meta in list(state.edges.items()):
            if pair not in wanted and not edge_meta.get("observed_until"):
                state.edges[pair] = {**edge_meta, "observed_until": shot.day}

    # ── writing ────────────────────────────────────────────────────────────

    def _write(self, state: State) -> None:
        """Every faction, committee, member and edge of *state*."""
        with NodeWriter(self.store) as writer:
            for collection, nodes in (
                (COLLECTION_FACTIONS, state.factions),
                (COLLECTION_COMMITTEES, state.committees),
            ):
                writer.add_all(
                    Node(
                        collection=collection,
                        key=key,
                        labels=[CHAMBER_EK],
                        props=props,
                    )
                    for key, props in sorted(nodes.items())
                )
            writer.add_all(node for _, node in sorted(state.members.items()))
        assign_member_slugs(self.store)
        writer_ = EdgeWriter(self.store, what="MEMBER_OF edges of the Eerste Kamer")
        for (source, target), edge_meta in sorted(state.edges.items()):
            writer_.add(
                source, target, RELATION_MEMBER_OF, source=EDGE_SOURCE, meta=edge_meta
            )
        writer_.flush()


def _observed(
    stored: dict[str, Any] | None, shot: Snapshot, since: str
) -> dict[str, Any]:
    """``chamber``, ``observed_from`` (kept while it stays observed), ``observed_until``
    (none: it is seen on the day of *shot*), ``retrieved_on`` (that day) and ``data_since``
    (of the first snapshot)."""
    open_ = stored is not None and not stored.get("observed_until")
    return {
        "chamber": CHAMBER_EK,
        "observed_from": stored["observed_from"] if open_ and stored else shot.day,
        "observed_until": None,
        "retrieved_on": shot.day,
        "data_since": since,
    }


def _last_read(versions: Iterable[dict[str, Any]]) -> str:
    """The last day the pages were read (``last_read_on``; else ``read_on``)."""
    return max(
        (
            str(meta(r).get("last_read_on") or meta(r).get("read_on") or "")
            for r in versions
        ),
        default="",
    )


def _read_on(state: State, day: str) -> None:
    """``retrieved_on`` *day* on what the last snapshot shows (nothing ended), when the
    pages were read later than that snapshot."""
    if not day:
        return
    for props in [*state.factions.values(), *state.committees.values()]:
        if not props.get("observed_until"):
            props["retrieved_on"] = max(day, props.get("retrieved_on") or "")
    for path, node in list(state.members.items()):
        ek = node.props.get("ek") or {}
        if not ek.get("observed_until"):
            read = max(day, ek.get("retrieved_on") or "")
            state.members[path] = _member(
                node.key or "", {**node.props, "ek": {**ek, "retrieved_on": read}}
            )
