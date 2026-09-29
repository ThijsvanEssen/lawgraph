"""``lawgraph curated``: the lists kept by hand (``data/curated/``, ``core.curated``).

    lawgraph curated list                       every list, its file and how many entries
    lawgraph curated list <list>                the entries of one list
    lawgraph curated check [<list>] [--db]      what is wrong with the lists (--db: also
                                                against the database: faction keys)
    lawgraph curated set <list> <key> [<json>] [--after KEY | --first]
    lawgraph curated remove <list> <key>

``set`` gives *key* the JSON value (``'{"color": "#003082", "aliases": []}'``; none for a
list of keys such as ``left-right``), in its place or at the end; ``--after`` and ``--first``
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
    if db and name in (None, "left-right"):
        from lawgraph.db import ArangoStore

        store = ArangoStore()
        found += database_problems(store)
        for note in database_notes(store):
            print(note)
    return found


def database_problems(store: Any) -> list[str]:
    """What the database says is wrong: a faction with seats that ``left-right`` does not
    place (it would sit at the right end, whatever its politics). A key of the list that no
    faction has is no problem here: a partial database lacks factions; ``database_notes``
    names them."""
    from lawgraph.db.queries.committees import get_factions

    placed = LISTS["left-right"].entries()
    return [
        f"left-right: {doc['_key']} ({(doc.get('props') or {}).get('abbreviation')}) has "
        "seats but no place: `lawgraph curated set left-right <key> --after <key>`"
        for doc in get_factions(store, active=True)
        if int((doc.get("props") or {}).get("seats") or 0) > 0
        and doc["_key"] not in placed
    ]


def database_notes(store: Any) -> list[str]:
    """The keys of ``left-right`` no faction in the database has (a typo, or a faction the
    database does not hold)."""
    from lawgraph.db.queries.committees import get_factions

    known = {doc["_key"] for doc in get_factions(store)}
    return [
        f"left-right: {key}: no faction in the database has this key"
        for key in LISTS["left-right"].entries()
        if known and key not in known
    ]


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
