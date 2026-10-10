"""Normalize the seats of the Eerste Kamer day by day, term by term (``lg_ek_terms``,
``lg_ek_seats``).

A term begins with the seats each list won at its election, as the Kiesraad counted them
(``retrieve kiesraad``), on the day the new Kamer was installed. Then every change the Kamer's
pages tell (``retrieve eerstekamer-mutations``; and the merges and renames a faction's own
page tells, from the composition ``retrieve eerstekamer-composition`` keeps) is walked
(``core.ek_changes.walk``): a stretch per day the seats changed, with the changes of that
day in the source's words. A faction is matched by the names today's list, the term's
Kiesraad lists and the items' texts give it (``core.ek_changes.known_factions``). A term
that does not add up (a change whose faction is not known, a faction short of seats, more
than 75, a past term that does not end on 75) is not ``checked``; the current term is
checked against today's composition, per faction. Both tables are written again whole.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_EK_COMPOSITION,
    RAW_KIND_EK_MUTATION,
    RAW_KIND_EK_MUTATIONS,
    RAW_KIND_KIESRAAD_EK_RESULT,
    SOURCE_EERSTEKAMER,
    SOURCE_KIESRAAD,
)
from lawgraph.core import eerstekamer_composition as composition
from lawgraph.core import ek_changes
from lawgraph.core.kiesraad import ElectionResult, parse_ek_result
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db.queries import ek_seats
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

FACTIONS_PATH = "/fracties"


def installed_on(election: str) -> str:
    """The day a Kamer elected on *election* (ISO) was installed: the Tuesday two weeks after
    the week of the election, as every Eerste Kamer since 2003 was."""
    day = dt.date.fromisoformat(election)
    tuesday = day - dt.timedelta(days=day.weekday()) + dt.timedelta(days=1)
    return (tuesday + dt.timedelta(days=14)).isoformat()


class EerstekamerMutationsNormalizePipeline(NormalizePipelineBase):
    """The seats of the Eerste Kamer per term and stretch, from the Kiesraad's results and
    the changes the Kamer's pages tell."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        # every term again, whatever the window: a term is walked from its start
        def records(source: str, kind: str) -> list[dict[str, Any]]:
            return list(self._iter_raw_sources(source=source, kinds=[kind]))

        return {
            "results": records(SOURCE_KIESRAAD, RAW_KIND_KIESRAAD_EK_RESULT),
            "terms": records(SOURCE_EERSTEKAMER, RAW_KIND_EK_MUTATIONS),
            "items": records(SOURCE_EERSTEKAMER, RAW_KIND_EK_MUTATION),
            "composition": records(SOURCE_EERSTEKAMER, RAW_KIND_EK_COMPOSITION),
        }

    def normalize_nodes(self, raw: dict[str, Any], result: PipelineResult) -> Any:
        elections = self._elections(raw["results"])
        if not elections:
            logger.warning("No result of an election of the Eerste Kamer is stored.")
            return {}
        pages = {
            str(r["external_id"]): self._payload_text(r) or ""
            for r in raw["composition"]
        }
        today = composition.factions(pages.get(FACTIONS_PATH, ""))
        lineage = [
            change
            for path, page in pages.items()
            if path.startswith("/fractie/")
            for change in ek_changes.faction_history(page)
        ]
        read, spelled = self._changes(raw["items"])
        factions = {_name(f): ek_changes.aliases(_name(f), f.path) for f in today}
        terms, stretches = self._walk(
            elections, lineage + read, (factions, spelled), today
        )
        self._write(terms, stretches)
        result.updated += len(stretches)
        for term in terms:
            logger.info(
                "Eerste Kamer from %s: %s; %s",
                term["start"],
                "checked" if term["checked"] else "not checked",
                "; ".join(term["mismatches"]) or "no mismatches",
            )
        return {"terms": terms}

    def build_edges(self, raw: Any, normalized: Any) -> None:
        return None

    # ── reading ────────────────────────────────────────────────────────────

    def _elections(
        self, records: Iterable[dict[str, Any]]
    ) -> list[tuple[ElectionResult, dict[str, Any]]]:
        found = []
        for record in records:
            parsed = parse_ek_result(self._payload_text(record) or "")
            if parsed is not None:
                meta = self._meta(record)
                found.append(
                    (parsed, {"url": meta.get("url"), "read_on": meta.get("read_on")})
                )
        return sorted(found, key=lambda e: e[0].date)

    def _changes(
        self, records: Iterable[dict[str, Any]]
    ) -> tuple[list[ek_changes.Change], list[str]]:
        """The changes the items tell, and the factions they spell out in full."""
        changes: list[ek_changes.Change] = []
        spelled: list[str] = []
        for record in records:
            meta = self._meta(record)
            date, headline = meta.get("date"), meta.get("headline")
            if not date or not headline:
                continue
            item = ek_changes.article(self._payload_text(record) or "", date, headline)
            read = ek_changes.read(item)
            spelled += ek_changes.spelled_out(item.text)
            if read.unread:
                logger.warning("Not read as a change (%s): %s", date, headline)
            changes += read.changes
        return changes, spelled

    # ── walking ────────────────────────────────────────────────────────────

    def _walk(
        self,
        elections: list[tuple[ElectionResult, dict[str, Any]]],
        changes: list[ek_changes.Change],
        names: tuple[dict[str, set[str]], list[str]],
        today: list[composition.Listed],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        terms, stretches = [], []
        starts = [installed_on(e.date) for e, _ in elections]
        last_day = dt.date.today().isoformat()
        for n, (election, source) in enumerate(elections):
            start = starts[n]
            end = (
                (
                    dt.date.fromisoformat(starts[n + 1]) - dt.timedelta(days=1)
                ).isoformat()
                if n + 1 < len(starts)
                else last_day
            )
            factions = ek_changes.known_factions(
                names[0], election.seats, changes, names[1]
            )
            seats, _ = ek_changes.start_seats(election.seats, factions)
            walked = ek_changes.walk(
                start, seats, ek_changes.canonical(changes, factions), end
            )
            mismatches = list(walked.mismatches)
            last = walked.stretches[-1].seats
            if n + 1 == len(elections):
                mismatches += _against(last, today) if today else []
            elif sum(last.values()) != ek_changes.SEATS:
                mismatches.append(
                    f"{end}: the term ends with {sum(last.values())} seats"
                )
            terms.append(
                {
                    "start": start,
                    "election": election.code,
                    "source": {"kiesraad": source},
                    "checked": not mismatches,
                    "mismatches": mismatches,
                }
            )
            for stretch in walked.stretches:
                stretches.append(
                    {
                        "from_date": stretch.from_date,
                        "to_date": stretch.to_date
                        or (end if n + 1 < len(elections) else None),
                        "term": start,
                        "seats": stretch.seats,
                        "events": [asdict(e) for e in stretch.events],
                    }
                )
        return terms, stretches

    def _write(
        self, terms: list[dict[str, Any]], stretches: list[dict[str, Any]]
    ) -> None:
        ek_seats.write(self.store, terms, stretches)


def _against(seats: dict[str, int], today: list[composition.Listed]) -> list[str]:
    """How the walked seats of the current term differ from today's composition."""
    walked = {ek_changes.faction_key(k): (k, v) for k, v in seats.items()}
    listed = {ek_changes.faction_key(_name(f)): f for f in today}
    found = []
    for key in sorted(set(walked) | set(listed)):
        have = walked.get(key, ("", 0))[1]
        want = listed[key].seats if key in listed else 0
        if have != (want or 0):
            name = _name(listed[key]) if key in listed else walked[key][0]
            found.append(f"today: {name} {have} walked, {want} on the site")
    return found


def _name(faction: composition.Listed) -> str:
    """The name a faction of today's list goes by: its abbreviation, else its name."""
    return faction.abbreviation or faction.name
