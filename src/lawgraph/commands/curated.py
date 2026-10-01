"""``lawgraph curated``: the lists kept by hand (``data/curated/``, ``core.curated``).

    lawgraph curated list                       every list, its file and how many entries
    lawgraph curated list <list>                the entries of one list
    lawgraph curated check [<list>] [--db]      what is wrong with the lists (--db: also
                                                against the database: faction keys,
                                                instruments abbreviated)
    lawgraph curated set <list> <key> [<json>] [--after KEY | --first]
    lawgraph curated remove <list> <key>

``set`` gives *key* the JSON value (``'{"color": "#003082", "aliases": []}'``; none for a
list of keys such as ``general-courts``), in its place or at the end; ``--after`` and ``--first``
place it in an ordered list. A change that makes the list wrong is not written. Commit what
``set`` and ``remove`` change; ``lawgraph check`` checks every list.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from lawgraph.core.curated import LISTS, Entries, place, problems
from lawgraph.core.models import PipelineResult


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    shown = sub.add_parser("list", help="The lists, or the entries of one.")
    shown.add_argument("name", nargs="?", choices=sorted(LISTS))
    checked = sub.add_parser("check", help="What is wrong with the lists.")
    checked.add_argument("name", nargs="?", choices=sorted(LISTS))
    checked.add_argument("--db", action="store_true", help="Also against the database.")
    changed = sub.add_parser("set", help="Give a key a value.")
    changed.add_argument("name", choices=sorted(LISTS))
    changed.add_argument("key")
    changed.add_argument("value", nargs="?", help="JSON; none for a list of keys.")
    where = changed.add_mutually_exclusive_group()
    where.add_argument("--after", help="Place it after this key (an ordered list).")
    where.add_argument("--first", action="store_true", help="Place it first.")
    removed = sub.add_parser("remove", help="Remove a key.")
    removed.add_argument("name", choices=sorted(LISTS))
    removed.add_argument("key")
    args = parser.parse_args(argv)

    result = PipelineResult()
    if args.action == "list":
        _list(args.name)
    elif args.action == "check":
        for problem in check(args.name, db=args.db):
            print(problem)
            result.add_error(problem)
        if not result.errors:
            print("The curated lists are in order.")
    else:
        for problem in _change(args):
            result.add_error(problem)
    return result


def _list(name: str | None) -> None:
    if name is None:
        for curated in LISTS.values():
            print(
                f"{curated.name:<22} {len(curated.entries()):>4}  {curated.file:<22} "
                f"{curated.description}"
            )
        return
    for key, value in LISTS[name].entries().items():
        print(
            key if value is None else f"{key}: {json.dumps(value, ensure_ascii=False)}"
        )


def check(name: str | None = None, *, db: bool = False) -> list[str]:
    """What is wrong with the lists (one of them with *name*); with *db* also against the
    database."""
    found = [p for p in problems() if name is None or p.startswith(f"{name}: ")]
    if db and name in (None, "seating", "phases", "instrument-abbreviations"):
        from lawgraph.db import GraphStore

        store = GraphStore()
        found += [
            p for p in database_problems(store) if name is None or p.startswith(name)
        ]
        for note in database_notes(store):
            print(note)
    return found


def database_problems(store: Any) -> list[str]:
    """What the database says is wrong with the lists: the seating plan
    (``_seating_problems``) and the abbreviations of instruments the graph does not have."""
    return _seating_problems(store) + _abbreviation_problems(store)


def _abbreviation_problems(store: Any) -> list[str]:
    """An abbreviation kept for an instrument no node of the graph is: a typing error in its
    id, or an instrument that is not loaded; the abbreviation then cites nothing."""
    from lawgraph.config.constants import COLLECTION_INSTRUMENTS
    from lawgraph.core.models import make_node_key

    entries = LISTS["instrument-abbreviations"].entries()
    keys = {law_id: make_node_key(law_id) for law_id in entries}
    present = store.existing_keys(COLLECTION_INSTRUMENTS, set(keys.values()))
    return [
        f"instrument-abbreviations: {law_id} "
        f"({', '.join((value or {}).get('abbreviations') or [])}): no instrument in the "
        "graph has this id"
        for law_id, value in entries.items()
        if keys[law_id] not in present
    ]


def _seating_problems(store: Any) -> list[str]:
    """What the database says is wrong with the seating plan: a faction with seats that it
    does not place (it would sit at the right end), and a faction whose number of seats
    differs from the plan's (a split, a new faction, elections: the Kamer then draws a new
    plan). A seat that changed after the plan (a new member in it) is only a note
    (``database_notes``), as is a key of the plan no faction has (a partial database)."""
    from lawgraph.db.queries.committees import get_factions

    placed = LISTS["seating"].entries()
    found = []
    for doc in get_factions(store, active=True):
        props = doc.get("props") or {}
        seats = int(props.get("seats") or 0)
        key, name = doc["_key"], props.get("abbreviation")
        if seats <= 0:
            continue
        if key not in placed:
            found.append(
                f"seating: {key} ({name}) has seats but no place in the seating plan: take "
                "it from the plan of the Tweede Kamer (`lawgraph curated set seating`)"
            )
        elif placed[key].get("seats") != seats:
            found.append(
                f"seating: {key} ({name}) has {seats} seats, the plan {placed[key].get('seats')}"
                ": take the new plan of the Tweede Kamer (wie zit waar)"
            )
    return found


def database_notes(store: Any) -> list[str]:
    """What the database tells of the lists without making them wrong: of the seating plan
    a seat that changed after the plan's date (a replacement within a faction leaves the
    seating as it is), and a key of the plan no faction in the database has (a typo, or a
    faction a partial database does not hold); of the phases a value of the Kamer no record
    in the database has (a typo, a spelling the Kamer changed, or a partial database)."""
    from lawgraph.db.queries.committees import get_factions
    from lawgraph.db.queries.dossiers import tk_values

    factions = get_factions(store)
    known = {doc["_key"] for doc in factions}
    notes = [
        f"seating: {key}: no faction in the database has this key"
        for key in LISTS["seating"].entries()
        if known and key not in known
    ]
    dated = str((LISTS["seating"].document().get("source") or {}).get("dated") or "")
    changed = max(
        (
            str((d.get("props") or {}).get("seats_changed_on") or "")
            for d in factions
            if (d.get("props") or {}).get("active")
        ),
        default="",
    )
    if dated and changed > dated:
        notes.append(
            f"seating: a seat changed on {changed}, after the plan of {dated} (the seating "
            "changes only when the numbers of seats do)"
        )
    in_use = tk_values(store)
    for phase, value in LISTS["phases"].entries().items():
        for part in ("documents", "activities", "decisions"):
            notes += [
                f"phases: {phase}: no record in the database has the {part[:-1]} {v!r}"
                for v in (value or {}).get(part) or []
                if in_use[part] and v not in in_use[part]
            ]
    return notes


def _change(args: argparse.Namespace) -> list[str]:
    curated = LISTS[args.name]
    entries = curated.entries()
    if args.action == "remove":
        if args.key not in entries:
            return [f"{args.name}: {args.key}: not in the list"]
        new: Entries = {k: v for k, v in entries.items() if k != args.key}
    else:
        value: Any = json.loads(args.value) if args.value is not None else None
        after = "" if args.first else args.after
        if after is not None and not curated.ordered:
            return [f"{args.name}: an unordered list; no --after or --first"]
        try:
            new = place(entries, args.key, value, after)
        except KeyError as exc:
            return [f"{args.name}: {exc.args[0]}"]
    wrong = [p for p in problems({args.name: new}) if p.startswith(f"{args.name}: ")]
    if wrong:
        return [*wrong, f"{args.name}: not written"]
    curated.store(new)
    print(f"{args.name}: {args.action} {args.key}; wrote {curated.path}.")
    return []
