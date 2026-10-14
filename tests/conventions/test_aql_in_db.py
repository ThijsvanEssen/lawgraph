"""Queries are written in ``db/`` only. Pipelines, commands and the API call a function of
``db/queries/`` and do not touch the driver handle.
"""

from __future__ import annotations

import pathlib

import pytest

from tests.paths import SRC
from tests.source_scan import DB, DRIVER_CALL, aql_in, python_files


def test_the_aql_scan_tells_a_query_from_prose() -> None:
    """The guards below are only worth having if they match queries and nothing else."""
    assert aql_in('A = f"FOR d IN {COLLECTION_X}\\n  FILTER d.x == @x\\n  RETURN d"')
    assert aql_in('A = "FOR a IN annexes RETURN a._key"')
    assert aql_in('A = "FILTER r.fetched_at >= @since"')
    assert aql_in("A = \"FOR d IN view SEARCH ANALYZER(d.text == @q, 'text_nl')\"")
    assert not aql_in('"""For every record in the list, return the key."""')
    assert not aql_in('"""FOR a IN the list: nothing more."""')
    assert DRIVER_CALL.search("rows = self.store.query(aql, bind)")
    assert DRIVER_CALL.search("store.collection(COLLECTION_X).get(key)")
    assert not DRIVER_CALL.search("raw_queries.iter_raw_records(self.store, source=s)")


@pytest.mark.parametrize(
    "path",
    [p for p in python_files() if DB not in p.parents],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_aql_is_only_written_in_db(path: pathlib.Path) -> None:
    lines = aql_in(path.read_text())
    assert not lines, (
        f"{path.relative_to(SRC)}:{lines} holds AQL; queries live in "
        f"db/queries/, the code outside db/ calls a function there."
    )


@pytest.mark.parametrize(
    "path",
    [
        p
        for top in ("pipelines", "commands", "api")
        for p in sorted((SRC / top).rglob("*.py"))
    ],
    ids=lambda p: str(p.relative_to(SRC)),
)
def test_pipelines_commands_and_api_do_not_use_the_driver(path: pathlib.Path) -> None:
    calls = [
        number
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if DRIVER_CALL.search(line)
    ]
    assert not calls, (
        f"{path.relative_to(SRC)}:{calls} queries the database itself; the queries and "
        f"collection access live in db/."
    )
