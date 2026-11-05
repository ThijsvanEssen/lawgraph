#!/usr/bin/env python3
"""Counts of how the site is used, for the decision on the native apps; read only, and only
counts leave it: never a network of the request log, a path or a search term.

    python ops/usage-counts.py routes DAYS   the request log of the journal, per kind of route
    python ops/usage-counts.py terms DIR     the day and month files of the search terms, per
                                             kind of term (citation, law name, free text)

The request log holds no User-Agent and no query string, so neither the device, nor a bot, nor
``?mode=netwerk`` can be read from it: ``nodes/neighborhood`` (what the canvas asks) stands in
for the Netwerk, and counts requests, not views.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# The readable addresses (core/readable_paths.py) and the other pages of the site; any other
# first part of a path is `overig`, so a path never shows in the output.
PAGES = frozenset(
    """activiteiten actueel api bronnen bundels commissies docs dossiers explore fracties
    kabinetten kamerstukken leden ministeries onderwerpen over privacy stb stcrt stemmingen
    toezeggingen trb uitspraken voorwaarden wetten zaken zoeken""".split()
)
# The first part behind /api/ of the routes of the API (`lawgraph openapi`).
API_ROUTES = frozenset(
    """activities annexes articles cabinets chains commitments committees decisions documents
    dossiers factions feed feed.atom health instruments judgments lookup members ministries
    nodes parliament parties paths relationships resolve search stats""".split()
)
OTHER = "overig"
# A line of ``log_requests``: its date and, past the id and the network (not read), the rest.
_REQUEST = re.compile(r"\[[0-9a-f]{8}\] \S+ ([A-Z]+) (/.*?) → (\d)\d\d\b")
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2}) ")
_DAY_FILE = re.compile(r"^search-(\d{4}-\d{2}-\d{2})\.json$")
_MONTH_FILE = re.compile(r"^search-(\d{4}-\d{2})\.json$")
CITATION = "citatie"
LAW_NAME = "wetnaam"
FREE_TEXT = "vrije tekst"


def route_kind(path: str) -> tuple[str, str]:
    """``(pagina|api|overig, kind)`` of a path of the request log."""
    parts = [p for p in path.split("/") if p]
    if parts[:1] == ["render"]:
        return "pagina", _page_kind(parts[1:])
    if parts[:1] == ["api"]:
        return "api", _api_kind(parts[1:])
    return OTHER, OTHER


def _page_kind(parts: list[str]) -> str:
    if not parts:
        return "start"
    if parts[0] == "wetten" and len(parts) == 4 and parts[2] in ("artikel", "bijlage"):
        return f"wetten/{parts[2]}"
    return parts[0] if parts[0] in PAGES else OTHER


def _api_kind(parts: list[str]) -> str:
    if parts[-1:] == ["neighborhood"] and parts[0] == "nodes":
        return "nodes/neighborhood"
    return parts[0] if parts[:1] and parts[0] in API_ROUTES else OTHER


def count_requests(lines: Iterable[str]) -> tuple[Counter[Any], Counter[Any], int]:
    """The requests per ``(surface, kind, column)`` and per ``(day, surface)``, and how many
    lines looked like a request and could not be read."""
    routes: Counter[Any] = Counter()
    days: Counter[Any] = Counter()
    unread = 0
    for line in lines:
        found = _REQUEST.search(line)
        date = _DATE.match(line)
        if found is None or date is None:
            unread += " → " in line
            continue
        method, path, status = found.groups()
        surface, kind = route_kind(path)
        routes[surface, kind, "alle"] += 1
        routes[surface, kind, f"{status}xx"] += 1
        routes[surface, kind, "HEAD"] += method == "HEAD"
        days[date[1], surface] += 1
    return routes, days, unread


def print_requests(routes: Counter[Any], days: Counter[Any], unread: int) -> None:
    columns = ["alle", "HEAD", "2xx", "3xx", "4xx", "5xx"]
    surfaces = ["pagina", "api", OTHER]
    dated = sorted({day for day, _ in days})
    print(f"periode: {dated[0]} tot en met {dated[-1]}" if dated else "periode: leeg")
    print(f"dagen met verzoeken: {len(dated)}; regels niet gelezen: {unread}")
    print("\nsoort\troute\t" + "\t".join(columns))
    kinds = sorted(
        {key[:2] for key in routes}, key=lambda k: -routes[k[0], k[1], "alle"]
    )
    for surface, kind in kinds:
        counts = [str(routes[surface, kind, column]) for column in columns]
        print(f"{surface}\t{kind}\t" + "\t".join(counts))
    print("\ndag\t" + "\t".join(surfaces))
    for day in dated:
        print(day + "\t" + "\t".join(str(days[day, s]) for s in surfaces))


def journal_lines(days: int) -> Iterator[str]:
    """The lines of the API in the journal, as they come; fails when journalctl fails."""
    command = ["journalctl", "-u", "lawgraph-api", "--since", f"-{days} days"]
    with subprocess.Popen(
        [*command, "-o", "cat", "--no-pager"],
        stdout=subprocess.PIPE,
        text=True,
        errors="replace",
    ) as journal:
        assert journal.stdout is not None
        yield from journal.stdout
    if journal.returncode != 0:
        raise SystemExit(f"journalctl: exit {journal.returncode}")


def term_kind(parser: Any, term: str) -> str:
    """What the search reads *term* as: a notation of ``core.notation``, the name or
    abbreviation of a law, or words."""
    if parser.parse(term) is not None:
        return CITATION
    if any(match.tier in ("code", "title") for match in parser.law_matches(term)):
        return LAW_NAME
    return FREE_TEXT


def count_terms(parser: Any, directory: Path) -> list[tuple[str, str, Counter[str]]]:
    """Per file of *directory*, oldest first: its period, how complete it is, and the asks
    and the different terms per kind (``"<kind>"``, ``"<kind> termen"``)."""
    periods = []
    for path in sorted(directory.glob("search-*.json")):
        if day := _DAY_FILE.match(path.name):
            period, scope = day[1], "volledig"
        elif month := _MONTH_FILE.match(path.name):
            period, scope = month[1], "alleen termen die vaak gevraagd zijn"
        else:
            continue
        counts: Counter[str] = Counter()
        for term, asked in json.loads(path.read_text(encoding="utf-8")).items():
            kind = term_kind(parser, term)
            counts[kind] += int(asked)
            counts[f"{kind} termen"] += 1
        periods.append((period, scope, counts))
    return periods


def print_terms(periods: list[tuple[str, str, Counter[str]]]) -> None:
    kinds = [CITATION, LAW_NAME, FREE_TEXT]
    header = "\t".join(f"{kind}\t{kind} termen" for kind in kinds)
    print(f"periode\t{header}\tbereik")
    complete: Counter[str] = Counter()
    for period, scope, counts in periods:
        cells = "\t".join(
            f"{counts[kind]}\t{counts[f'{kind} termen']}" for kind in kinds
        )
        print(f"{period}\t{cells}\t{scope}")
        if scope == "volledig":
            complete += counts
    cells = "\t".join(
        f"{complete[kind]}\t{complete[f'{kind} termen']}" for kind in kinds
    )
    print(
        f"som van de volledige dagen\t{cells}\t(een term op twee dagen telt twee keer)"
    )


class _ReadOnlyStore:
    """What ``load_notation_parser`` asks of a store, in a session PostgreSQL keeps read-only;
    a ``GraphStore`` would first bring the schema up to date. Keeps nothing between calls."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def query(self, statement: str, params: Any = None, **_options: Any) -> Any:
        return self._conn.execute(statement, params).fetchall()


def _parser_of_the_graph() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    from lawgraph.config.settings import DB_NAME, DB_URL
    from lawgraph.db.queries.search.parser import load_notation_parser

    conn = psycopg.connect(
        f"{DB_URL.rstrip('/')}/{DB_NAME}",
        application_name="usage-counts",
        options="-c default_transaction_read_only=on -c statement_timeout=600s",
        row_factory=dict_row,
    )
    with conn:
        store = _ReadOnlyStore(conn)
        # without laws every article and law name would count as free text
        if not store.query("SELECT 1 FROM instruments LIMIT 1"):
            raise SystemExit(f"no instruments in {DB_NAME}")
        return load_notation_parser(store)  # type: ignore[arg-type]


def main(argv: list[str]) -> None:
    match argv:
        case ["routes", days]:
            print_requests(*count_requests(journal_lines(int(days))))
        case ["terms", directory]:
            print_terms(count_terms(_parser_of_the_graph(), Path(directory)))
        case _:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
