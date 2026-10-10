"""Normalize the pages of the members of the Eerste Kamer (``retrieve eerstekamer-persons``)
into their periods in its factions: ``ek_faction_memberships`` on the member, as the page
of the member says them (``core.ek_persons``).

A page is the member's whom the composition gave it (``ek.path``), else the member of the
Tweede Kamer born on the day the page gives whose surname ends its name, when exactly one
is; else none, and its periods are counted, not written (a former member of the Eerste
Kamer who never sat in the Tweede Kamer has no member, and no page to show them on). A
period's faction is the faction of the Eerste Kamer of that abbreviation or name observed
on its first day (as the votes match it, ``eerstekamer_votes.faction_of``); a faction gone
before the composition was first read has none (its votes have no edges either). Every
period is checked against the changes of ``normalize eerstekamer-mutations``: one whose
start or end no change of that member nor a term's first day dates within a week is
counted and named in the log, not changed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_EK_PERSON,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_persons
from lawgraph.core.ek_changes import member_key
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import NodeWriter
from lawgraph.db.queries import ek_seats
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase
from lawgraph.pipelines.normalize.eerstekamer_votes import faction_of

logger = get_logger(__name__)

# How far a period's start or end may lie from the change that dates it (days).
CHECK_DAYS = 7


class EerstekamerPersonsNormalizePipeline(NormalizePipelineBase):
    """The periods of the members of the Eerste Kamer in its factions."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        # every page again, whatever the window: a member's periods are written whole
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER, kinds=[RAW_KIND_EK_PERSON], batch_size=50
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> dict[str, Any]:
        pages = {
            str(r["external_id"]): page
            for r in raw
            if (page := ek_persons.person_page(self._payload_text(r) or ""))
        }
        members = self._members(pages)
        factions = self._factions()
        events = _by_member(ek_seats.events(self.store))
        unmatched = sorted(path for path in pages if path not in members)
        no_faction, off = 0, []
        with NodeWriter(self.store) as writer:
            for path, key in members.items():
                page = pages[path]
                periods = []
                for period in page.periods:
                    faction = faction_of(factions, period.faction, period.from_date)
                    no_faction += faction is None
                    periods.append(_period(period, faction))
                    off += [
                        f"{page.name}: {day}"
                        for day in (period.from_date, period.to_date)
                        if day and not _dated(day, page.name, events)
                    ]
                writer.add(
                    Node(
                        collection=COLLECTION_MEMBERS,
                        type=NodeType.MEMBER,
                        key=key,
                        props={"ek_faction_memberships": periods},
                    )
                )
                result.updated += 1
        logger.info(
            "Eerste Kamer persons: %d pages, %d of a member, %d of no member (former members "
            "without a page); %d periods of a faction not in the graph; %d days no change "
            "dates: %s",
            len(pages),
            len(members),
            len(unmatched),
            no_faction,
            len(off),
            "; ".join(off[:30]) or "none",
        )
        return {"members": members, "unmatched": unmatched}

    def build_edges(self, raw: Any, normalized: Any) -> None:
        return None

    def _members(self, pages: dict[str, ek_persons.PersonPage]) -> dict[str, str]:
        """The key of the member of each page that has one: by the composition's path, else
        the one member of the Tweede Kamer born that day whose surname ends the name."""
        found = normalize_ek.members_by_ek_path(self.store, sorted(pages))
        dates = sorted({p.birth_date for p in pages.values() if p.birth_date})
        born: dict[str, list[dict[str, Any]]] = {}
        for row in normalize_tk.members_born_on(self.store, dates):
            born.setdefault(str(row["birth_date"]), []).append(row)
        for path, page in pages.items():
            if path in found or not page.birth_date:
                continue
            name = page.name.rsplit("(", 1)[0].strip().casefold()
            same = [
                row
                for row in born.get(page.birth_date, [])
                if row.get("family_name")
                and name.endswith(str(row["family_name"]).casefold())
            ]
            if len(same) == 1:
                found[path] = str(same[0]["key"])
        return found

    def _factions(self) -> dict[str, list[dict[str, Any]]]:
        """The factions of the Eerste Kamer by each name a page may give them."""
        factions: dict[str, list[dict[str, Any]]] = {}
        for row in normalize_ek.ek_factions_named(self.store):
            for name in {row.get("abbreviation"), row.get("name")} - {None}:
                factions.setdefault(str(name), []).append(row)
        return factions


def _period(
    period: ek_persons.Period, faction: dict[str, Any] | None
) -> dict[str, Any]:
    """A period as ``faction_memberships`` of the Tweede Kamer holds one."""
    return {
        "faction_id": faction["id"] if faction else None,
        "faction_key": faction["key"] if faction else None,
        "abbreviation": (faction or {}).get("abbreviation") or period.faction,
        "name": (faction or {}).get("name") or period.faction,
        "from_date": period.from_date,
        "to_date": period.to_date,
        "chamber": "EK",
    }


def _by_member(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The days of the changes of each member (by ``member_key``), and of every term's
    first day under ``""``."""
    found: dict[str, list[str]] = {}
    for row in rows:
        who = "" if row["kind"] == "term" else member_key(row.get("member"))
        found.setdefault(who, []).append(str(row["date"]))
    return found


def _dated(day: str, name: str, events: dict[str, list[str]]) -> bool:
    """Whether a change of the member named *name*, or a term's first day, dates *day*
    within ``CHECK_DAYS`` (a last day: the day after it)."""
    who = member_key(name.rsplit("(", 1)[0])
    wanted = dt.date.fromisoformat(day)
    for other in events.get(who, []) + events.get("", []):
        try:
            gap = abs((dt.date.fromisoformat(other[:10]) - wanted).days)
        except ValueError:
            continue
        if gap <= CHECK_DAYS:
            return True
    return False
